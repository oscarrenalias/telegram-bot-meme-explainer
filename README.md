# Overview

Telegram bot that when prompted, takes memes (images) posted in a message, sends it to an OpenAI GPT to retrieve an explanation. The LLM will:

- extract the image
- process the image, including identifying the text
- automatically identify the right language of the meme
- provide an explanation in response

The LLM's response will be returned as a message with basic formatting.

The bot is triggered using a mention (@-bot) via a reply to a message that contains the image with the meme. 

The bot is integrated with OpenAI GPT-4. Integration with OpenAI is done via the LangChain python library.

# Running

1. Build docker container:

```
docker build -t telegram-bot-meme-explainer:latest .
```

2. Run container:

```
docker run \
    -e TELEGRAM_BOT_TOKEN=bot_token \
    -e OPENAI_API_KEY=openai_key \
    -i telegram-bot-meme-explainer:latest
```

Please provide the right values for variables TELEGRAM_BOT_TOKEN and OPENAI_API_KEY accordingly.

# Adding the bot to a gruop

The bot has only been tested with a group, as this was its indended purpose.

When added to a group, it will require admin access to the channel so that it can process all messages.

# Securing the bot

By default it can be added to any group, and it will listen to all messages. In order to restrict the groups it can respond to use parameter BOT_AUTHORIZED_GROUPS as a comma-separated list of group ids, as follows:

```
docker run ... -e BOT_AUTHORIZED_GROUPS=123,456,789
```