class SectionNotFoundError(KeyError):
    pass


class LocatorIndexLoadError(RuntimeError):
    pass


class ExerciseNotFoundError(KeyError):
    pass


class ExerciseCatalogUnavailableError(RuntimeError):
    pass


class ExerciseIndexLoadError(RuntimeError):
    pass
