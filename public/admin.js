document.addEventListener('DOMContentLoaded', () => {
    const gameForm = document.getElementById('game-form');

    gameForm.addEventListener('submit', (event) => {
        event.preventDefault();

        const formData = new FormData(gameForm);
        const groups = [];

        for (let i = 1; i <= 4; i++) {
            const connection = formData.get(`g${i}-connection`);
            const level = formData.get(`g${i}-level`);
            const words = formData.getAll(`g${i}-word`);
            groups.push({ connection, level, words });
        }

        const newGame = {
            id: Date.now(), // Use a timestamp for a unique ID
            groups: groups
        };

        fetch('/api/games', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(newGame),
        })
        .then(response => response.json())
        .then(data => {
            console.log('Success:', data);
            alert('Game saved successfully!');
            gameForm.reset();
        })
        .catch((error) => {
            console.error('Error:', error);
            alert('Error saving game.');
        });
    });
});
