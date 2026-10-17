"""Project Levitate - Visual Flight Physics Lab (workstream B).

Stand-alone 6-DOF rigid-body flight simulator for a Tech-Deck-sized hoverboard, with a cascaded
flight controller, ideal-vs-reality constraint modes, solver integration and a FastAPI backend.
All quantities are SI. Frames: world x forward, y left, z up (ground plane z = 0);
body x forward (board length), y left, z up; quaternions are scalar-first, body -> world.
"""
__version__ = "0.1.0"
