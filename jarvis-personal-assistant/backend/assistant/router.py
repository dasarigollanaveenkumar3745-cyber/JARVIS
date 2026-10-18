from assistant.intents import detect_intent


def process_message(text: str):

    intent = detect_intent(text)

    return {
        "intent": intent,
        "message": f"Detected intent: {intent}"
    }
``
