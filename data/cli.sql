CREATE TABLE players (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    debut_date DATE,
    championships_won INT DEFAULT 0
);

CREATE TABLE teams (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    founded_year INT,
    championships_won INT DEFAULT 0
);

CREATE TABLE player_team (
    player_id INT,
    team_id INT,
    start_date DATE,
    end_date DATE,
    PRIMARY KEY (player_id, team_id),
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (team_id) REFERENCES teams(id)
);