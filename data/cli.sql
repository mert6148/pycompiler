CREATE TABLE players (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    debut_date DATE,
    championships_won INT DEFAULT 0
);
