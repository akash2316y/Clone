"""Holds the running CloneManager so handlers can reach it without circular imports."""
manager = None


def set_manager(m):
    global manager
    manager = m
