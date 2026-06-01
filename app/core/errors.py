class BookNotFoundError(FileNotFoundError):
    pass


class SectionNotFoundError(KeyError):
    pass


class FigureNotFoundError(KeyError):
    pass
