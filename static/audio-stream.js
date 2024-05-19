document.addEventListener('DOMContentLoaded', function() {
    var audio = document.querySelector('audio');
    audio.autoplay = true;  // autoplay 속성 추가

    var mediaSource = new MediaSource();

    audio.src = URL.createObjectURL(mediaSource);

    mediaSource.addEventListener('sourceopen', function() {
        var sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');

        fetch('/audio-stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'text/plain'
            },
            body: '{"query": "현재 영업활동 프로세스 인스턴스들의 상태를 알려줘"}'
        })
            .then(response => {
                const reader = response.body.getReader();

                function push() {
                    reader.read().then(({ done, value }) => {
                        if (done) {
                            mediaSource.endOfStream();
                            return;
                        }
                        if (!sourceBuffer.updating) {
                            sourceBuffer.appendBuffer(value);
                            audio.play()
                        }
                        sourceBuffer.addEventListener('updateend', push, { once: true });
                        
                    }).catch(error => {
                        console.error('Error fetching audio stream', error);
                    });
                }

                push();
            });
    });
});
