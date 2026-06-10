use hbb_common::{
    get_time,
    message_proto::{CodecRuntimeStatus, Message, VoiceCallRequest, VoiceCallResponse},
};
use scrap::CodecFormat;
use std::collections::HashMap;

#[derive(Debug, Default)]
pub struct QualityStatus {
    pub speed: Option<String>,
    pub fps: HashMap<usize, i32>,
    pub delay: Option<i32>,
    pub target_bitrate: Option<i32>,
    pub codec_format: Option<CodecFormat>,
    pub chroma: Option<String>,
    pub encoding_runtime_status: Option<CodecRuntimeStatus>,
    pub decoding_runtime_status: Option<CodecRuntimeStatus>,
}

pub fn codec_runtime_status_label(status: CodecRuntimeStatus) -> &'static str {
    match status {
        CodecRuntimeStatus::CodecRuntimeSoftware => "No",
        CodecRuntimeStatus::CodecRuntimeHardware => "Yes",
        CodecRuntimeStatus::CodecRuntimeMixed => "Mixed",
        CodecRuntimeStatus::CodecRuntimeUnknown => "-",
    }
}

pub fn codec_runtime_status_from_iter<I>(statuses: I) -> CodecRuntimeStatus
where
    I: IntoIterator<Item = CodecRuntimeStatus>,
{
    let mut has_hardware = false;
    let mut has_software = false;

    for status in statuses {
        match status {
            CodecRuntimeStatus::CodecRuntimeHardware => has_hardware = true,
            CodecRuntimeStatus::CodecRuntimeSoftware => has_software = true,
            CodecRuntimeStatus::CodecRuntimeMixed => {
                has_hardware = true;
                has_software = true;
            }
            CodecRuntimeStatus::CodecRuntimeUnknown => {}
        }
    }

    match (has_hardware, has_software) {
        (true, true) => CodecRuntimeStatus::CodecRuntimeMixed,
        (true, false) => CodecRuntimeStatus::CodecRuntimeHardware,
        (false, true) => CodecRuntimeStatus::CodecRuntimeSoftware,
        _ => CodecRuntimeStatus::CodecRuntimeUnknown,
    }
}

#[inline]
pub fn new_voice_call_request(is_connect: bool) -> Message {
    let mut req = VoiceCallRequest::new();
    req.is_connect = is_connect;
    req.req_timestamp = get_time();
    let mut msg = Message::new();
    msg.set_voice_call_request(req);
    msg
}

#[inline]
pub fn new_voice_call_response(request_timestamp: i64, accepted: bool) -> Message {
    let mut resp = VoiceCallResponse::new();
    resp.accepted = accepted;
    resp.req_timestamp = request_timestamp;
    resp.ack_timestamp = get_time();
    let mut msg = Message::new();
    msg.set_voice_call_response(resp);
    msg
}
