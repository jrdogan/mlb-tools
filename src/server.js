const express = require('express');
const path = require('path');
const fs = require('fs').promises;

const app = express();
const port = process.env.PORT || 3000;

// Serve static files from the 'public' directory
app.use(express.static(path.join(__dirname, '..', 'public')));

// Serve game data from the 'data' directory
app.use('/data', express.static(path.join(__dirname, '..', 'data')));

const gamesFilePath = path.join(__dirname, '..', 'data', 'games.json');

// Middleware to parse JSON bodies
app.use(express.json());

// API endpoint to get all games
app.get('/api/games', async (req, res) => {
    try {
        const data = await fs.readFile(gamesFilePath, 'utf8');
        res.json(JSON.parse(data));
    } catch (err) {
        res.status(500).send('Error reading games data.');
    }
});

// API endpoint to create a new game
app.post('/api/games', async (req, res) => {
    try {
        const newGame = req.body;
        const data = await fs.readFile(gamesFilePath, 'utf8');
        const gamesData = JSON.parse(data);
        gamesData.games.push(newGame);
        await fs.writeFile(gamesFilePath, JSON.stringify(gamesData, null, 2));
        res.status(201).json(newGame);
    } catch (err) {
        res.status(500).send('Error saving game.');
    }
});

app.listen(port, () => {
  console.log(`Server is running on http://localhost:${port}`);
});
