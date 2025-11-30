class Logger:
    def __init__(self):
        import logging as _logging
        self.logger = _logging.getLogger("MQTTClient")
        handler = _logging.StreamHandler()
        formatter = _logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        # Avoid adding duplicate handlers if Logger instantiated multiple times
        if not self.logger.handlers:
            self.logger.addHandler(handler)
        self.logger.setLevel(_logging.DEBUG)
