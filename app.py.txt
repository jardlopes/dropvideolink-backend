form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const videoUrl = urlInput.value.trim();
    if(!videoUrl) return;

    resultState.classList.add('hidden');
    loadingState.classList.remove('hidden');
    loadingStatusText.textContent = "Conectando ao motor de extração real...";

    try {
        // Substitua pela URL real que o Render te der
        const response = await fetch('https://SEU-BACKEND-NO-RENDER.onrender.com/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: videoUrl })
        });

        const data = await response.json();

        if (data.success) {
            loadingState.classList.add('hidden');
            resultState.classList.remove('hidden');
            
            // Atualiza os dados reais na tela
            document.getElementById('video-title').textContent = data.title;
            document.getElementById('video-duration').textContent = data.duration || 'N/A';
            
            // Configura o botão de download para abrir o link real extraído pelo yt-dlp
            document.querySelectorAll('.quality-btn').forEach(btn => {
                btn.onclick = () => {
                    window.open(data.download_url, '_blank');
                    showToast("Download iniciado com sucesso!");
                };
            });
            
            showToast("Vídeo processado com sucesso!");
        } else {
            loadingState.classList.add('hidden');
            showToast("Erro ao processar o link. Verifique se é público.");
        }
    } catch (err) {
        loadingState.classList.add('hidden');
        showToast("Falha de conexão com o servidor de download.");
    }
});