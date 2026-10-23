import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
import av

st.set_page_config(page_title="Phone Call Demo", page_icon="📞")

st.title("📞 South India Farmer Helpline - Live Phone Call Demo")
st.write("Speak from your phone microphone. The audio comes directly to the app.")

class AudioProcessor:
    def recv(self, frame):
        audio = frame.to_ndarray()
        st.session_state["last_audio_shape"] = audio.shape
        return frame

webrtc_ctx = webrtc_streamer(
    key="farmer-call",
    mode=WebRtcMode.SENDRECV,
    audio_receiver_size=256,
    media_stream_constraints={
        "video": False,
        "audio": True,
    },
    async_processing=True,
    audio_processor_factory=AudioProcessor,
)

if webrtc_ctx.state.playing:
    st.success("🎙️ Live call connected! Speak now from your phone.")

    if "last_audio_shape" in st.session_state:
        st.write(f"📡 Receiving audio frames: {st.session_state['last_audio_shape']}")
else:
    st.info("Press START above to connect the call.")