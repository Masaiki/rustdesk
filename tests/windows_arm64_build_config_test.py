import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class WindowsArm64BuildConfigTest(unittest.TestCase):
    def test_scrap_build_uses_arch_specific_windows_triplet(self):
        build_rs = read("libs/scrap/build.rs")

        self.assertIn('"arm64-windows-static"', build_rs)
        self.assertIsNone(
            re.search(
                r'else if target_os == "windows"\s*\{\s*"x64-windows-static"\.to_owned\(\)\s*\}',
                build_rs,
            )
        )

    def test_build_py_accepts_explicit_windows_rust_target(self):
        build_py = read("build.py")

        self.assertIn("--target", build_py)
        self.assertIn("--zip", build_py)
        self.assertIn("aarch64-pc-windows-msvc", build_py)
        self.assertRegex(build_py, r"cargo\{cargo_config_args\(target\)\} build .*rust_target_args")
        self.assertIn("windows-arm64", build_py)
        self.assertIn("build/windows/arm64/runner/Release/", build_py)
        self.assertIn("RUSTDESK_RUST_TARGET", build_py)
        self.assertIn("FLUTTER_WINDOWS_TARGET_PLATFORM", build_py)
        self.assertIn("rustdesk-{version}-windows-arm64.zip", build_py)
        self.assertIn("Skip vram", build_py)
        self.assertNotIn("Skip hwcodec", build_py)
        self.assertIn("cargo_config_args", build_py)
        self.assertIn("libsodium", build_py)
        self.assertIn("opus.lib", build_py)
        self.assertIn("dxguid.lib", build_py)
        self.assertIn("avcodec.lib", build_py)

    def test_flutter_cmake_uses_targeted_librustdesk_dll(self):
        cmake = read("flutter/windows/CMakeLists.txt")

        self.assertIn("RUSTDESK_RUST_TARGET", cmake)
        self.assertIn("target/$ENV{RUSTDESK_RUST_TARGET}", cmake)
        self.assertIn("librustdesk.dll", cmake)

    def test_windows_arm64_vcpkg_manifest_avoids_x64_hardware_codecs(self):
        manifest = read("vcpkg.json")
        ffmpeg_port = read("res/vcpkg/ffmpeg/portfile.cmake")

        self.assertIn("(((windows & !arm64) | linux) & static)", manifest)
        self.assertIn("(windows & static & (x86 | x64))", manifest)
        self.assertIn('--arch=aarch64 --enable-cross-compile', ffmpeg_port)
        self.assertIn('VCPKG_TARGET_ARCHITECTURE STREQUAL "arm64"', ffmpeg_port)
        self.assertIn('arm64-windows*) OPTIONS_arm64=" --disable-asm --disable-x86asm"', read("res/vcpkg/ffmpeg/build.sh.in"))

    def test_windows_arm64_hwcodec_uses_media_foundation(self):
        hwcodec = read("libs/scrap/src/common/hwcodec.rs")
        lockfile = read("Cargo.lock")

        self.assertIn('("h264_mf", DataFormat::H264)', hwcodec)
        self.assertIn('("hevc_mf", DataFormat::H265)', hwcodec)
        self.assertIn('target_os = "windows", target_arch = "aarch64"', hwcodec)
        self.assertIn("available_ram_encoders(ctx, vram_string)", hwcodec)
        self.assertIn("hwcodec#1c6bb84360f5ebf3b04cabde52f153c4ff29a949", lockfile)


if __name__ == "__main__":
    unittest.main()
