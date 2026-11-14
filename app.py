async function baixarVideo() {
    const url = document.getElementById("videoUrl").value;

    try {
        const response = await fetch(
            "http://127.0.0.1:5000/api/download",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ url })
            }
        );

        if (!response.ok) {
            const erro = await response.json();
            throw new Error(erro.error);
        }

        const blob = await response.blob();

        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "video";
        link.click();

        URL.revokeObjectURL(link.href);

    } catch (error) {
        alert(error.message);
    }
}
