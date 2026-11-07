class Repository:
    def __init__(self, session_factory):
        self._session_factory = session_factory