def replace_in_file(filepath, search_text, replace_text):
    with open(filepath, 'r') as f:
        content = f.read()
    if search_text in content:
        content = content.replace(search_text, replace_text)
        with open(filepath, 'w') as f:
            f.write(content)

replace_in_file("bene/observe/base.py",
                "def __exit__(self, *exc: Any) -> bool:\n        return False",
                "def __exit__(self, *exc: Any) -> None:\n        pass")
replace_in_file("bene/observe/base.py", "def __exit__(self, *exc: Any) -> bool: ...", "def __exit__(self, *exc: Any) -> None: ...")

replace_in_file("bene/observe/langfuse.py",
                "def __exit__(self, *exc: Any) -> bool:\n        if not self._is_root:\n            _safe(self._obj.end)\n        return False",
                "def __exit__(self, *exc: Any) -> None:\n        if not self._is_root:\n            _safe(self._obj.end)")

replace_in_file("bene/observe/langfuse.py",
                "def __exit__(self, *exc: Any) -> bool:\n        if self._cm is not None:\n            _safe(lambda: self._cm.__exit__(*exc))\n        if self._propagate_cm is not None:\n            _safe(lambda: self._propagate_cm.__exit__(*exc))\n        return False",
                "def __exit__(self, *exc: Any) -> None:\n        if self._cm is not None:\n            _safe(lambda: self._cm.__exit__(*exc))\n        if self._propagate_cm is not None:\n            _safe(lambda: self._propagate_cm.__exit__(*exc))")

replace_in_file("bene/observe/langfuse.py",
                "self._propagate_cm = _safe(lambda: _propagate_attributes(self._trace_fields))",
                "self._propagate_cm = _safe(lambda: _propagate_attributes(self._trace_fields or {}))")
