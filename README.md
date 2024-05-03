# Yahoo Auction, Mercari, Surugaya Discord Bot

This project is a Discord bot designed to find second hand items on Yahoo Auction, Mercari and Surugaya and alert the user on a Discord server.

It's a rewrite from the original code by vlourme which you can find here https://github.com/vlourme/yahoo-auction-alert-discord-bot

Currently this bot is very opinionated to my needs, but I'm planning to make it more configurable in the future.

## Installation

Before you start the installation process, ensure you have Python installed on your system. You can download Python from [here](https://www.python.org/downloads/). This project is compatible with Python 3.8 and above.

Follow these steps to install the project:

1. Clone this repository to your local machine using `https://github.com/koenvdheuvel/yahoo-auction-alert-discord-bot.git`.

```bash
git clone https://github.com/koenvdheuvel/yahoo-auction-alert-discord-bot.git
```

2. Navigate to the project directory.

```bash
cd yahoo-auction-alert-discord-bot
```

3. Install the required dependencies.

```bash
pip install -r requirements.txt
```

## Setting Up the Environment Variables

Create a `.env` file in the root directory of the project. This file will store the Discord token required for the bot to function. The `.env` file should look something like this:

```bash
BOT_TOKEN=your-discord-token
CHECK_INTERVAL=1800
ENABLE_YAHOO_AUCTION=true
ENABLE_MERCARI=true
ENABLE_SURUGAYA=true
```

Replace `your-discord-token` with the actual Discord bot token.

## Running the Bot

You can start the bot by running the `main.py` script.

```bash
python main.py
```

The bot should now be running and scanning Yahoo Auction and Mercari for new articles.

## Important Notes

1. This bot also relies on the https://zenmarket.jp and https://fromjapan.co.jp unofficial API's to fetch items, any API change could break this bot.
2. Make sure to keep your Discord token secure and never share it with anyone.

## Contributing

We welcome contributions to this project. Please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

If you encounter any issues or have questions, please open an issue on this GitHub repository. We will try our best to assist you.
