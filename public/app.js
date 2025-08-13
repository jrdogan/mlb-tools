document.addEventListener('DOMContentLoaded', () => {
    const gameBoard = document.getElementById('game-board');
    const livesContainer = document.getElementById('lives');
    const submitButton = document.getElementById('submit-button');
    const shuffleButton = document.getElementById('shuffle-button');

    let game;
    let words = [];
    let selectedWords = [];
    let lives = 4;
    let solvedGroups = 0;

    fetch('/data/games.json')
        .then(response => response.json())
        .then(data => {
            game = data.games[0];
            words = game.groups.flatMap(group => group.words);
            shuffle(words);
            populateBoard();
        });

    submitButton.addEventListener('click', handleSubmit);
    shuffleButton.addEventListener('click', handleShuffle);

    function shuffle(array) {
        for (let i = array.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [array[i], array[j]] = [array[j], array[i]];
        }
    }

    function populateBoard() {
        gameBoard.innerHTML = '';
        words.forEach(word => {
            const tile = document.createElement('div');
            tile.classList.add('word-tile');
            tile.textContent = word;
            tile.addEventListener('click', () => selectTile(tile));
            gameBoard.appendChild(tile);
        });
    }

    function selectTile(tile) {
        if (tile.classList.contains('solved')) return;

        if (selectedWords.length < 4 && !tile.classList.contains('selected')) {
            tile.classList.add('selected');
            selectedWords.push(tile.textContent);
        } else if (tile.classList.contains('selected')) {
            tile.classList.remove('selected');
            selectedWords = selectedWords.filter(word => word !== tile.textContent);
        }
    }

    function handleSubmit() {
        if (selectedWords.length !== 4) {
            alert('Please select exactly 4 words.');
            return;
        }

        const group = findGroup(selectedWords);

        if (group) {
            handleCorrectSubmission(group);
        } else {
            handleIncorrectSubmission();
        }
    }

    function findGroup(selected) {
        return game.groups.find(group => {
            const groupWords = group.words;
            return selected.every(word => groupWords.includes(word)) && groupWords.every(word => selected.includes(word));
        });
    }

    function handleCorrectSubmission(group) {
        solvedGroups++;
        const solvedGroupContainer = document.createElement('div');
        solvedGroupContainer.classList.add('solved-group', group.level);

        const connectionDiv = document.createElement('div');
        connectionDiv.classList.add('connection');
        connectionDiv.textContent = group.connection;

        const wordsDiv = document.createElement('div');
        wordsDiv.classList.add('words');
        wordsDiv.textContent = group.words.join(', ');

        solvedGroupContainer.appendChild(connectionDiv);
        solvedGroupContainer.appendChild(wordsDiv);

        // Insert the solved group at the top of the game container
        const gameContainer = document.getElementById('game-container');
        gameContainer.insertBefore(solvedGroupContainer, gameBoard);

        // Remove solved words from the board and the words array
        words = words.filter(word => !group.words.includes(word));
        selectedWords = [];
        populateBoard();

        if (solvedGroups === 4) {
            setTimeout(() => alert('You win!'), 100);
        }
    }

    function handleIncorrectSubmission() {
        lives--;
        updateLives();

        const selectedTiles = Array.from(gameBoard.children).filter(tile => tile.classList.contains('selected'));
        selectedTiles.forEach(tile => {
            tile.classList.add('shake');
            setTimeout(() => {
                tile.classList.remove('shake');
                tile.classList.remove('selected');
            }, 500);
        });

        selectedWords = [];

        if (lives === 0) {
            setTimeout(() => alert('You lose!'), 100);
        }
    }

    function handleShuffle() {
        shuffle(words);
        populateBoard();
    }

    function updateLives() {
        const dots = livesContainer.querySelectorAll('.dot');
        for (let i = 0; i < dots.length; i++) {
            if (i < lives) {
                dots[i].style.backgroundColor = '#bbb';
            } else {
                dots[i].style.backgroundColor = '#fff';
            }
        }
    }
});
