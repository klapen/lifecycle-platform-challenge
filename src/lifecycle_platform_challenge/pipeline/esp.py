class ESPClient:
    """Provided interface — do not modify send_batch's signature."""

    def send_batch(self, campaign_id: str, recipients: list[dict]):
        """Sends a batch of recipients to the ESP.
        Returns a Response with .status_code and .json()"""
        raise NotImplementedError
