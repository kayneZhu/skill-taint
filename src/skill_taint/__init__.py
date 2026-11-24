"""Cross-episode skill poisoning demo.

The enforcement code is the integrity lattice, grounding check, skill store,
instruction-channel quarantine, and tool-call endorsement gate. The mock
planner is a scripted simulation of an agent that follows skills it is given.
It is not a language model.
"""

__version__ = "0.2.0"
