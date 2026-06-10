#!/usr/bin/env python3

import os
import pathlib
import platform
import zipfile
import urllib.request
import shutil
import hashlib
import argparse
import sys
from pathlib import Path

windows = platform.platform().startswith('Windows')
osx = platform.platform().startswith(
    'Darwin') or platform.platform().startswith("macOS")
hbb_name = 'rustdesk' + ('.exe' if windows else '')
exe_path = 'target/release/' + hbb_name
if windows:
    flutter_build_dir = 'build/windows/x64/runner/Release/'
elif osx:
    flutter_build_dir = 'build/macos/Build/Products/Release/'
else:
    flutter_build_dir = 'build/linux/x64/release/bundle/'
flutter_build_dir_2 = f'flutter/{flutter_build_dir}'
skip_cargo = False


def rust_target_args(target):
    return f' --target {target}' if target else ''


def rust_release_dir(target):
    return f'target/{target}/release' if target else 'target/release'


def rust_exe_path(target):
    return f'{rust_release_dir(target)}/{hbb_name}'


def macos_flutter_arch(target):
    if target == 'aarch64-apple-darwin':
        return 'arm64'
    if target == 'x86_64-apple-darwin':
        return 'x64'
    return ''


def windows_flutter_target_platform(target):
    if target == 'aarch64-pc-windows-msvc':
        return 'windows-arm64'
    if target == 'x86_64-pc-windows-msvc' or not target:
        return ''
    return ''


def windows_flutter_build_dir(target):
    if target == 'aarch64-pc-windows-msvc':
        return 'build/windows/arm64/runner/Release/'
    return 'build/windows/x64/runner/Release/'


def cargo_path(path):
    return Path(path).as_posix()


def vcpkg_installed_root():
    installed_root = os.environ.get('VCPKG_INSTALLED_ROOT')
    if installed_root:
        return Path(installed_root)
    vcpkg_root = os.environ.get('VCPKG_ROOT')
    if vcpkg_root:
        return Path(vcpkg_root) / 'installed'
    return None


def write_windows_arm64_cargo_config(target):
    if target != 'aarch64-pc-windows-msvc':
        return ''

    installed_root = vcpkg_installed_root()
    if installed_root is None:
        sys.stderr.write('VCPKG_ROOT or VCPKG_INSTALLED_ROOT is required for Windows arm64 builds.\n')
        sys.exit(-1)

    triplet_root = installed_root / 'arm64-windows-static'
    lib_dir = triplet_root / 'lib'
    include_dir = triplet_root / 'include'
    required_libs = [lib_dir / 'opus.lib', lib_dir / 'libsodium.lib']
    missing = [p for p in required_libs if not p.exists()]
    if missing:
        sys.stderr.write('Missing Windows arm64 vcpkg libraries:\n')
        for path in missing:
            sys.stderr.write(f'  {path}\n')
        sys.stderr.write('Install them with vcpkg for triplet arm64-windows-static.\n')
        sys.exit(-1)

    config_dir = Path('target') / 'cargo-config'
    rustflags = [
        '-Ctarget-feature=+crt-static',
        '-Clink-arg=dxguid.lib',
        '-Clink-arg=mfuuid.lib',
        '-Clink-arg=strmiids.lib',
        f'-Clink-arg={cargo_path(lib_dir / "opus.lib")}',
    ]
    for lib in ('avcodec.lib', 'avutil.lib', 'avformat.lib'):
        lib_path = lib_dir / lib
        if lib_path.exists():
            rustflags.append(f'-Clink-arg={cargo_path(lib_path)}')

    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / 'windows-arm64-vcpkg.toml'
    rustflags_toml = '\n'.join(f'    "{flag}",' for flag in rustflags)
    config_path.write_text(f'''[target.aarch64-pc-windows-msvc]
rustflags = [
{rustflags_toml}
]

[target.aarch64-pc-windows-msvc.sodium]
rustc-link-lib = ["static=libsodium"]
rustc-link-search = ["native={cargo_path(lib_dir)}"]
include = "{cargo_path(include_dir)}"
lib = "{cargo_path(lib_dir)}"
''', encoding='utf-8')
    return str(config_path)


def configure_windows_arm64_vcpkg_env(target):
    if target != 'aarch64-pc-windows-msvc':
        return None

    installed_root = vcpkg_installed_root()
    if installed_root is None:
        sys.stderr.write('VCPKG_ROOT or VCPKG_INSTALLED_ROOT is required for Windows arm64 builds.\n')
        sys.exit(-1)

    triplet_root = installed_root / 'arm64-windows-static'
    source_include = triplet_root / 'include' / 'opus'
    source_lib = triplet_root / 'lib' / 'opus.lib'
    missing = [p for p in (source_include, source_lib) if not p.exists()]
    if missing:
        sys.stderr.write('Missing Windows arm64 opus files:\n')
        for path in missing:
            sys.stderr.write(f'  {path}\n')
        sys.stderr.write('Install opus with vcpkg for triplet arm64-windows-static.\n')
        sys.exit(-1)

    compat_root = Path('target') / 'vcpkg-arm64-magnum-opus'
    compat_triplet = compat_root / 'installed' / 'x64-windows-static'
    compat_include = compat_triplet / 'include' / 'opus'
    compat_lib = compat_triplet / 'lib'
    compat_lib.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_include, compat_include, dirs_exist_ok=True)
    shutil.copy2(source_lib, compat_lib / 'opus.lib')

    previous = {
        'VCPKG_ROOT': os.environ.get('VCPKG_ROOT'),
        'VCPKG_INSTALLED_ROOT': os.environ.get('VCPKG_INSTALLED_ROOT'),
    }
    os.environ['VCPKG_INSTALLED_ROOT'] = str(installed_root.resolve())
    os.environ['VCPKG_ROOT'] = str(compat_root.resolve())
    print(f'Using Windows arm64 vcpkg compatibility root for magnum-opus: {os.environ["VCPKG_ROOT"]}')
    return previous


def restore_env(previous):
    if previous is None:
        return
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def cargo_config_args(target):
    config_path = write_windows_arm64_cargo_config(target)
    return f' --config "{config_path}"' if config_path else ''


def build_output_zip_path(version, target):
    if target == 'aarch64-pc-windows-msvc':
        return f'rustdesk-{version}-windows-arm64.zip'
    return f'rustdesk-{version}-windows-x64.zip'


def zip_windows_flutter_bundle(version, target):
    output_zip = build_output_zip_path(version, target)
    bundle_dir = Path(flutter_build_dir_2)
    if not (bundle_dir / 'rustdesk.exe').exists():
        sys.stderr.write(f'Cannot find {bundle_dir / "rustdesk.exe"} for zip packaging.\n')
        sys.exit(-1)
    if Path(output_zip).exists():
        Path(output_zip).unlink()
    shutil.make_archive(Path(output_zip).with_suffix('').as_posix(), 'zip', bundle_dir)
    print(f'output location: {Path(output_zip).resolve()}')
    return output_zip


def get_deb_arch() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch is None:
        return "amd64"
    return custom_arch

def get_deb_extra_depends() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch == "armhf": # for arm32v7 libsciter-gtk.so
        return ", libatomic1"
    return ""

def system2(cmd):
    exit_code = os.system(cmd)
    if exit_code != 0:
        sys.stderr.write(f"Error occurred when executing: `{cmd}`. Exiting.\n")
        sys.exit(-1)


def get_version():
    with open("Cargo.toml", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("version"):
                return line.replace("version", "").replace("=", "").replace('"', '').strip()
    return ''


def parse_rc_features(feature):
    available_features = {}
    apply_features = {}
    if not feature:
        feature = []

    def platform_check(platforms):
        if windows:
            return 'windows' in platforms
        elif osx:
            return 'osx' in platforms
        else:
            return 'linux' in platforms

    def get_all_features():
        features = []
        for (feat, feat_info) in available_features.items():
            if platform_check(feat_info['platform']):
                features.append(feat)
        return features

    if isinstance(feature, str) and feature.upper() == 'ALL':
        return get_all_features()
    elif isinstance(feature, list):
        if windows:
            # download third party is deprecated, we use github ci instead.
            # feature.append('PrivacyMode')
            pass
        for feat in feature:
            if isinstance(feat, str) and feat.upper() == 'ALL':
                return get_all_features()
            if feat in available_features:
                if platform_check(available_features[feat]['platform']):
                    apply_features[feat] = available_features[feat]
            else:
                print(f'Unrecognized feature {feat}')
        return apply_features
    else:
        raise Exception(f'Unsupported features param {feature}')


def make_parser():
    parser = argparse.ArgumentParser(description='Build script.')
    parser.add_argument(
        '-f',
        '--feature',
        dest='feature',
        metavar='N',
        type=str,
        nargs='+',
        default='',
        help='Integrate features, windows only.'
             'Available: [Not used for now]. Special value is "ALL" and empty "". Default is empty.')
    parser.add_argument('--flutter', action='store_true',
                        help='Build flutter package', default=False)
    parser.add_argument(
        '--hwcodec',
        action='store_true',
        help='Enable feature hwcodec' + (
            '' if windows or osx else ', need libva-dev.')
    )
    parser.add_argument(
        '--vram',
        action='store_true',
        help='Enable feature vram, only available on windows now.'
    )
    parser.add_argument(
        '--portable',
        action='store_true',
        help='Build windows portable'
    )
    parser.add_argument(
        '--unix-file-copy-paste',
        action='store_true',
        help='Build with unix file copy paste feature'
    )
    parser.add_argument(
        '--skip-cargo',
        action='store_true',
        help='Skip cargo build process, only flutter version + Linux supported currently'
    )
    parser.add_argument(
        '--target',
        type=str,
        default=os.environ.get('RUSTDESK_BUILD_TARGET', ''),
        help='Rust target triple, for example aarch64-pc-windows-msvc'
    )
    if windows:
        parser.add_argument(
            '--skip-portable-pack',
            action='store_true',
            help='Skip packing, only flutter version + Windows supported'
        )
        parser.add_argument(
            '--zip',
            action='store_true',
            help='Package the Windows Flutter release bundle as a zip'
        )
    parser.add_argument(
        "--package",
        type=str
    )
    if osx:
        parser.add_argument(
            '--screencapturekit',
            action='store_true',
            help='Enable feature screencapturekit'
        )
    return parser


# Generate build script for docker
#
# it assumes all build dependencies are installed in environments
# Note: do not use it in bare metal, or may break build environments
def generate_build_script_for_docker():
    with open("/tmp/build.sh", "w") as f:
        f.write('''
            #!/bin/bash
            # environment
            export CPATH="$(clang -v 2>&1 | grep "Selected GCC installation: " | cut -d' ' -f4-)/include"
            # flutter
            pushd /opt
            wget https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.0.5-stable.tar.xz
            tar -xvf flutter_linux_3.0.5-stable.tar.xz
            export PATH=`pwd`/flutter/bin:$PATH
            popd
            # flutter_rust_bridge
            dart pub global activate ffigen --version 5.0.1
            pushd /tmp && git clone https://github.com/SoLongAndThanksForAllThePizza/flutter_rust_bridge --depth=1 && popd
            pushd /tmp/flutter_rust_bridge/frb_codegen && cargo install --path . --locked && popd
            pushd flutter && flutter pub get && popd
            ~/.cargo/bin/flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart
            # install vcpkg
            pushd /opt
            export VCPKG_ROOT=`pwd`/vcpkg
            git clone https://github.com/microsoft/vcpkg
            vcpkg/bootstrap-vcpkg.sh
            popd
            $VCPKG_ROOT/vcpkg install --x-install-root="$VCPKG_ROOT/installed"
            # build rustdesk
            ./build.py --flutter --hwcodec
        ''')
    system2("chmod +x /tmp/build.sh")
    system2("bash /tmp/build.sh")


# Downloading third party resources is deprecated.
# We can use this function in an offline build environment.
# Even in an online environment, we recommend building third-party resources yourself.
def download_extract_features(features, res_dir):
    import re

    proxy = ''

    def req(url):
        if not proxy:
            return url
        else:
            r = urllib.request.Request(url)
            r.set_proxy(proxy, 'http')
            r.set_proxy(proxy, 'https')
            return r

    for (feat, feat_info) in features.items():
        includes = feat_info['include'] if 'include' in feat_info and feat_info['include'] else []
        includes = [re.compile(p) for p in includes]
        excludes = feat_info['exclude'] if 'exclude' in feat_info and feat_info['exclude'] else []
        excludes = [re.compile(p) for p in excludes]

        print(f'{feat} download begin')
        download_filename = feat_info['zip_url'].split('/')[-1]
        checksum_md5_response = urllib.request.urlopen(
            req(feat_info['checksum_url']))
        for line in checksum_md5_response.read().decode('utf-8').splitlines():
            if line.split()[1] == download_filename:
                checksum_md5 = line.split()[0]
                filename, _headers = urllib.request.urlretrieve(feat_info['zip_url'],
                                                                download_filename)
                md5 = hashlib.md5(open(filename, 'rb').read()).hexdigest()
                if checksum_md5 != md5:
                    raise Exception(f'{feat} download failed')
                print(f'{feat} download end. extract bein')
                zip_file = zipfile.ZipFile(filename)
                zip_list = zip_file.namelist()
                for f in zip_list:
                    file_exclude = False
                    for p in excludes:
                        if p.match(f) is not None:
                            file_exclude = True
                            break
                    if file_exclude:
                        continue

                    file_include = False if includes else True
                    for p in includes:
                        if p.match(f) is not None:
                            file_include = True
                            break
                    if file_include:
                        print(f'extract file {f}')
                        zip_file.extract(f, res_dir)
                zip_file.close()
                os.remove(download_filename)
                print(f'{feat} extract end')


def external_resources(flutter, args, res_dir):
    features = parse_rc_features(args.feature)
    if not features:
        return

    print(f'Build with features {list(features.keys())}')
    if os.path.isdir(res_dir) and not os.path.islink(res_dir):
        shutil.rmtree(res_dir)
    elif os.path.exists(res_dir):
        raise Exception(f'Find file {res_dir}, not a directory')
    os.makedirs(res_dir, exist_ok=True)
    download_extract_features(features, res_dir)
    if flutter:
        os.makedirs(flutter_build_dir_2, exist_ok=True)
        for f in pathlib.Path(res_dir).iterdir():
            print(f'{f}')
            if f.is_file():
                shutil.copy2(f, flutter_build_dir_2)
            else:
                shutil.copytree(f, f'{flutter_build_dir_2}{f.stem}')


def get_features(args):
    features = ['inline'] if not args.flutter else []
    windows_arm64 = windows and args.target == 'aarch64-pc-windows-msvc'
    if args.hwcodec:
        features.append('hwcodec')
    if args.vram and windows_arm64:
        print('Skip vram: Windows arm64 build uses hwcodec Media Foundation instead of the current VRAM path.')
    elif args.vram:
        features.append('vram')
    if args.flutter:
        features.append('flutter')
    if args.unix_file_copy_paste:
        features.append('unix-file-copy-paste')
    if osx:
        if args.screencapturekit:
            features.append('screencapturekit')
    print("features:", features)
    return features


def generate_control_file(version):
    control_file_path = "../res/DEBIAN/control"
    system2('/bin/rm -rf %s' % control_file_path)

    content = """Package: rustdesk
Section: net
Priority: optional
Version: %s
Architecture: %s
Maintainer: rustdesk <info@rustdesk.com>
Homepage: https://rustdesk.com
Depends: libgtk-3-0t64 | libgtk-3-0, libxcb-randr0, libxdo3 | libxdo4, libxfixes3, libxcb-shape0, libxcb-xfixes0, libasound2t64 | libasound2, libsystemd0, curl, libva2, libva-drm2, libva-x11-2, libgstreamer-plugins-base1.0-0, libpam0g, gstreamer1.0-pipewire%s
Recommends: libayatana-appindicator3-1
Description: A remote control software.

""" % (version, get_deb_arch(), get_deb_extra_depends())
    file = open(control_file_path, "w")
    file.write(content)
    file.close()


def ffi_bindgen_function_refactor():
    # workaround ffigen
    system2(
        'sed -i "s/ffi.NativeFunction<ffi.Bool Function(DartPort/ffi.NativeFunction<ffi.Uint8 Function(DartPort/g" flutter/lib/generated_bridge.dart')


def build_flutter_deb(version, features):
    if not skip_cargo:
        system2(f'cargo build --locked --features {features} --lib --release')
        ffi_bindgen_function_refactor()
    os.chdir('flutter')
    system2('flutter build linux --release')
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk')
    system2('mkdir -p tmpdeb/etc/rustdesk/')
    system2('mkdir -p tmpdeb/etc/pam.d/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/rustdesk || true')
    system2(
        f'cp -r {flutter_build_dir}/* tmpdeb/usr/share/rustdesk/')
    system2(
        'cp ../res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
    system2(
        'cp ../res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
    system2(
        'cp ../res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
    system2(
        'cp ../res/startwm.sh tmpdeb/etc/rustdesk/')
    system2(
        'cp ../res/xorg.conf tmpdeb/etc/rustdesk/')
    system2(
        'cp ../res/pam.d/rustdesk.debian tmpdeb/etc/pam.d/rustdesk')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/rustdesk/files/polkit && chmod a+x tmpdeb/usr/share/rustdesk/files/polkit")

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    md5_file_folder("tmpdeb/")
    system2('dpkg-deb -b tmpdeb rustdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('rustdesk.deb', '../rustdesk-%s.deb' % version)
    os.chdir("..")


def build_deb_from_folder(version, binary_folder):
    os.chdir('flutter')
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk')
    system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/rustdesk || true')
    system2(
        f'cp -r ../{binary_folder}/* tmpdeb/usr/share/rustdesk/')
    system2(
        'cp ../res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
    system2(
        'cp ../res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
    system2(
        'cp ../res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/rustdesk/files/polkit && chmod a+x tmpdeb/usr/share/rustdesk/files/polkit")

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    md5_file_folder("tmpdeb/")
    system2('dpkg-deb -b tmpdeb rustdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('rustdesk.deb', '../rustdesk-%s.deb' % version)
    os.chdir("..")


def build_flutter_dmg(version, features, target):
    if not skip_cargo:
        # set minimum osx build target, now is 10.14, which is the same as the flutter xcode project
        system2(
            f'MACOSX_DEPLOYMENT_TARGET=10.14 cargo build --locked --features {features} --release{rust_target_args(target)}')
    # copy dylib
    release_dir = rust_release_dir(target)
    if target:
        Path('target/release').mkdir(parents=True, exist_ok=True)
        system2(f'cp {release_dir}/liblibrustdesk.dylib target/release/liblibrustdesk.dylib')
    system2(f'cp {release_dir}/liblibrustdesk.dylib {release_dir}/librustdesk.dylib')
    os.chdir('flutter')
    system2('flutter build macos --release')
    system2(f'cp -rf ../{release_dir}/service ./build/macos/Build/Products/Release/RustDesk.app/Contents/MacOS/')
    '''
    system2(
        "create-dmg --volname \"RustDesk Installer\" --window-pos 200 120 --window-size 800 400 --icon-size 100 --app-drop-link 600 185 --icon RustDesk.app 200 190 --hide-extension RustDesk.app rustdesk.dmg ./build/macos/Build/Products/Release/RustDesk.app")
    os.rename("rustdesk.dmg", f"../rustdesk-{version}.dmg")
    '''
    os.chdir("..")


def build_flutter_arch_manjaro(version, features):
    if not skip_cargo:
        system2(f'cargo build --locked --features {features} --lib --release')
    ffi_bindgen_function_refactor()
    os.chdir('flutter')
    system2('flutter build linux --release')
    system2(f'strip {flutter_build_dir}/lib/librustdesk.so')
    os.chdir('../res')
    system2('HBB=`pwd`/.. FLUTTER=1 makepkg -f')


def build_flutter_windows(version, features, skip_portable_pack, target, zip_bundle):
    previous_vcpkg_env = configure_windows_arm64_vcpkg_env(target)
    if not skip_cargo:
        system2(f'cargo{cargo_config_args(target)} build --locked --features {features} --lib --release{rust_target_args(target)}')
        restore_env(previous_vcpkg_env)
        if not os.path.exists(f"{rust_release_dir(target)}/librustdesk.dll"):
            print("cargo build failed, please check rust source code.")
            exit(-1)
    os.chdir('flutter')
    target_platform = windows_flutter_target_platform(target)
    if target:
        os.environ['RUSTDESK_RUST_TARGET'] = target
    else:
        os.environ.pop('RUSTDESK_RUST_TARGET', None)
    if target_platform:
        os.environ['FLUTTER_WINDOWS_TARGET_PLATFORM'] = target_platform
    else:
        os.environ.pop('FLUTTER_WINDOWS_TARGET_PLATFORM', None)
    system2('flutter build windows --release')
    os.chdir('..')
    shutil.copy2(f'{rust_release_dir(target)}/deps/dylib_virtual_display.dll',
                 flutter_build_dir_2)
    if zip_bundle:
        zip_windows_flutter_bundle(version, target)
    if skip_portable_pack:
        return
    os.chdir('libs/portable')
    system2('pip3 install -r requirements.txt')
    system2(
        f'python3 ./generate.py -f ../../{flutter_build_dir_2} -o . -e ../../{flutter_build_dir_2}/rustdesk.exe')
    os.chdir('../..')
    if os.path.exists('./rustdesk_portable.exe'):
        os.replace('./target/release/rustdesk-portable-packer.exe',
                   './rustdesk_portable.exe')
    else:
        os.rename('./target/release/rustdesk-portable-packer.exe',
                  './rustdesk_portable.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/rustdesk_portable.exe')
    os.rename('./rustdesk_portable.exe', f'./rustdesk-{version}-install.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/rustdesk-{version}-install.exe')


def main():
    global exe_path, flutter_build_dir, flutter_build_dir_2, skip_cargo
    parser = make_parser()
    args = parser.parse_args()
    if windows:
        flutter_build_dir = windows_flutter_build_dir(args.target)
        flutter_build_dir_2 = f'flutter/{flutter_build_dir}'
        exe_path = rust_exe_path(args.target)

    if os.path.exists(exe_path):
        os.unlink(exe_path)
    if os.path.isfile('/usr/bin/pacman'):
        system2('git checkout src/ui/common.tis')
    version = get_version()
    features = ','.join(get_features(args))
    flutter = args.flutter
    if not flutter:
        system2('python3 res/inline-sciter.py')
    print(args.skip_cargo)
    if args.skip_cargo:
        skip_cargo = True
    portable = args.portable
    package = args.package
    if package:
        build_deb_from_folder(version, package)
        return
    res_dir = 'resources'
    external_resources(flutter, args, res_dir)
    if windows:
        # build virtual display dynamic library
        os.chdir('libs/virtual_display/dylib')
        system2(f'cargo{cargo_config_args(args.target)} build --locked --release{rust_target_args(args.target)}')
        os.chdir('../../..')

        if flutter:
            build_flutter_windows(version, features, args.skip_portable_pack, args.target, args.zip)
            return
        release_dir = rust_release_dir(args.target)
        system2('cargo' + cargo_config_args(args.target) + ' build --locked --release --features ' + features + rust_target_args(args.target))
        # system2('upx.exe target/release/rustdesk.exe')
        system2(f'mv {release_dir}/rustdesk.exe {release_dir}/RustDesk.exe')
        pa = os.environ.get('P')
        if pa:
            # https://certera.com/kb/tutorial-guide-for-safenet-authentication-client-for-code-signing/
            system2(
                f'signtool sign /a /v /p {pa} /debug /f .\\cert.pfx /t http://timestamp.digicert.com  '
                f'{release_dir}\\rustdesk.exe')
        else:
            print('Not signed')
        system2(
            f'cp -rf {release_dir}/RustDesk.exe {res_dir}')
        os.chdir('libs/portable')
        system2('pip3 install -r requirements.txt')
        system2(
            f'python3 ./generate.py -f ../../{res_dir} -o . -e ../../{res_dir}/rustdesk-{version}-win7-install.exe')
        system2(f'mv ../../{res_dir}/rustdesk-{version}-win7-install.exe ../..')
    elif os.path.isfile('/usr/bin/pacman'):
        # pacman -S -needed base-devel
        system2("sed -i 's/pkgver=.*/pkgver=%s/g' res/PKGBUILD" % version)
        if flutter:
            build_flutter_arch_manjaro(version, features)
        else:
            system2('cargo build --locked --release --features ' + features)
            system2('git checkout src/ui/common.tis')
            system2('strip target/release/rustdesk')
            system2('ln -s res/pacman_install && ln -s res/PKGBUILD')
            system2('HBB=`pwd` makepkg -f')
        system2('mv rustdesk-%s-0-x86_64.pkg.tar.zst rustdesk-%s-manjaro-arch.pkg.tar.zst' % (
            version, version))
        # pacman -U ./rustdesk.pkg.tar.zst
    elif os.path.isfile('/usr/bin/yum'):
        system2('cargo build --locked --release --features ' + features)
        system2('strip target/release/rustdesk')
        system2(
            "sed -i 's/Version:    .*/Version:    %s/g' res/rpm.spec" % version)
        system2('HBB=`pwd` rpmbuild -ba res/rpm.spec')
        system2(
            'mv $HOME/rpmbuild/RPMS/x86_64/rustdesk-%s-0.x86_64.rpm ./rustdesk-%s-fedora28-centos8.rpm' % (
                version, version))
        # yum localinstall rustdesk.rpm
    elif os.path.isfile('/usr/bin/zypper'):
        system2('cargo build --locked --release --features ' + features)
        system2('strip target/release/rustdesk')
        system2(
            "sed -i 's/Version:    .*/Version:    %s/g' res/rpm-suse.spec" % version)
        system2('HBB=`pwd` rpmbuild -ba res/rpm-suse.spec')
        system2(
            'mv $HOME/rpmbuild/RPMS/x86_64/rustdesk-%s-0.x86_64.rpm ./rustdesk-%s-suse.rpm' % (
                version, version))
        # yum localinstall rustdesk.rpm
    else:
        if flutter:
            if osx:
                build_flutter_dmg(version, features, args.target)
                pass
            else:
                # system2(
                #     'mv target/release/bundle/deb/rustdesk*.deb ./flutter/rustdesk.deb')
                build_flutter_deb(version, features)
        else:
            system2('cargo --locked bundle --release --features ' + features)
            if osx:
                system2(
                    'strip target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk')
                system2(
                    'cp libsciter.dylib target/release/bundle/osx/RustDesk.app/Contents/MacOS/')
                # https://github.com/sindresorhus/create-dmg
                system2('/bin/rm -rf *.dmg')
                pa = os.environ.get('P')
                if pa:
                    system2('''
    # buggy: rcodesign sign ... path/*, have to sign one by one
    # install rcodesign via cargo install apple-codesign
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/libsciter.dylib
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app
    # goto "Keychain Access" -> "My Certificates" for below id which starts with "Developer ID Application:"
    codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/*
    codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app
    '''.format(pa))
                system2(
                    'create-dmg "RustDesk %s.dmg" "target/release/bundle/osx/RustDesk.app"' % version)
                os.rename('RustDesk %s.dmg' %
                          version, 'rustdesk-%s.dmg' % version)
                if pa:
                    system2('''
    # https://pyoxidizer.readthedocs.io/en/apple-codesign-0.14.0/apple_codesign.html
    # https://pyoxidizer.readthedocs.io/en/stable/tugger_code_signing.html
    # https://developer.apple.com/developer-id/
    # goto xcode and login with apple id, manager certificates (Developer ID Application and/or Developer ID Installer) online there (only download and double click (install) cer file can not export p12 because no private key)
    #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./rustdesk-{1}.dmg
    codesign -s "Developer ID Application: {0}" --force --options runtime ./rustdesk-{1}.dmg
    # https://appstoreconnect.apple.com/access/api
    # https://gregoryszorc.com/docs/apple-codesign/stable/apple_codesign_getting_started.html#apple-codesign-app-store-connect-api-key
    # p8 file is generated when you generate api key (can download only once)
    rcodesign notary-submit --api-key-path ../.p12/api-key.json  --staple rustdesk-{1}.dmg
    # verify:  spctl -a -t exec -v /Applications/RustDesk.app
    '''.format(pa, version))
                else:
                    print('Not signed')
            else:
                # build deb package
                system2(
                    'mv target/release/bundle/deb/rustdesk*.deb ./rustdesk.deb')
                system2('dpkg-deb -R rustdesk.deb tmpdeb')
                system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
                system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
                system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
                system2(
                    'cp res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
                system2(
                    'cp res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
                system2(
                    'cp res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
                system2(
                    'cp res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
                system2(
                    'cp res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
                os.system('mkdir -p tmpdeb/etc/rustdesk/')
                os.system('cp -a res/startwm.sh tmpdeb/etc/rustdesk/')
                os.system('mkdir -p tmpdeb/etc/X11/rustdesk/')
                os.system('cp res/xorg.conf tmpdeb/etc/X11/rustdesk/')
                os.system('cp -a DEBIAN/* tmpdeb/DEBIAN/')
                os.system('mkdir -p tmpdeb/etc/pam.d/')
                os.system('cp pam.d/rustdesk.debian tmpdeb/etc/pam.d/rustdesk')
                system2('strip tmpdeb/usr/bin/rustdesk')
                system2('mkdir -p tmpdeb/usr/share/rustdesk')
                system2('mv tmpdeb/usr/bin/rustdesk tmpdeb/usr/share/rustdesk/')
                system2('cp libsciter-gtk.so tmpdeb/usr/share/rustdesk/')
                md5_file_folder("tmpdeb/")
                system2('dpkg-deb -b tmpdeb rustdesk.deb; /bin/rm -rf tmpdeb/')
                os.rename('rustdesk.deb', 'rustdesk-%s.deb' % version)


def md5_file(fn):
    md5 = hashlib.md5(open('tmpdeb/' + fn, 'rb').read()).hexdigest()
    system2('echo "%s  /%s" >> tmpdeb/DEBIAN/md5sums' % (md5, fn))

def md5_file_folder(base_dir):
    base_path = Path(base_dir)
    for file in base_path.rglob('*'):
        if file.is_file() and 'DEBIAN' not in file.parts:
            relative_path = file.relative_to(base_path)
            md5_file(str(relative_path))


if __name__ == "__main__":
    main()
