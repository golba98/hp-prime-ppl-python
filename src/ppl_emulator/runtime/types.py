class PPLList(list):
    """1-indexed list for PPL compatibility."""
    def __call__(self, i):
        try:
            return super().__getitem__(int(i) - 1)
        except (IndexError, TypeError):
            return 0

    def __getitem__(self, i):
        if isinstance(i, slice):
            return PPLList(super().__getitem__(i))
        try:
            return super().__getitem__(int(i) - 1)
        except (IndexError, TypeError):
            return 0

    def __setitem__(self, i, val):
        try:
            super().__setitem__(int(i) - 1, val)
        except IndexError:
            # PPL automatically expands lists
            while len(self) < int(i):
                self.append(0)
            super().__setitem__(int(i) - 1, val)

    def __hash__(self):
        def make_hashable(obj):
            if isinstance(obj, (list, PPLList)):
                return tuple(make_hashable(x) for x in obj)
            return obj
        return hash(make_hashable(self))

    def __eq__(self, other: object) -> bool:
        try:
            return list(self) == list(other)  # pyre-ignore
        except TypeError:
            return False

class CASMock:
    def __call__(self, cmd):
        return 0.5
    def LambertW(self, z, k=0):
        return 0.5
