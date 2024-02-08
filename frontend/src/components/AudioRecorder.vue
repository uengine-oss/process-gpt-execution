<!-- src/components/AudioRecorder.vue -->
<template>
  <div>
    <button @mousedown="startRecording" @mouseup="stopRecording" @mouseleave="stopRecording">
      녹음 시작/중지
    </button>
    <div v-if="transcript">Transcript: {{ transcript }}</div> <!-- Add this line -->
  </div>
</template>

<script>
export default {
  name: 'AudioRecorder',
  data() {
    return {
      mediaRecorder: null,
      audioChunks: [],
      transcript: '', // Add this line
    };
  },
  methods: {
    async startRecording() {
      if (!navigator.mediaDevices) {
        alert('getUserMedia를 지원하지 않는 브라우저입니다.');
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.audioChunks = [];
      this.mediaRecorder.ondataavailable = e => {
        this.audioChunks.push(e.data);
      };
      this.mediaRecorder.start();
    },
    stopRecording() {
      // MediaRecorder의 상태가 'recording'인 경우에만 stop 메서드를 호출
      if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
        this.mediaRecorder.stop();
        this.mediaRecorder.onstop = async () => {
          const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
          this.uploadAudio(audioBlob);
        };
      }
    },
    async uploadAudio(audioBlob) {
      const formData = new FormData();
      formData.append('audio', audioBlob);

      try {
        const response = await fetch('http://localhost:8003/upload', {
          method: 'POST',
          body: formData,
        });
        const data = await response.json();
        console.log(data);
        this.transcript = data.transcript; // Add this line
      } catch (error) {
        console.error('Error:', error);
      }
    },
  },
};
</script>