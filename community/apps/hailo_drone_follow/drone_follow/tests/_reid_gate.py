"""Pairwise cosine-similarity gate for ReID gallery coherence.

Lives outside test_*.py so pytest does not collect it as a test, but both
test_sim_worlds.test_2_persons_diagonal_keeps_initial_target (the integration
gate) and test_reid_gallery_coherence_gate (the synthetic proof that the gate
fires on swapped galleries) read the thresholds from here, so they cannot
drift apart.
"""

# A clean gallery of one person across pose changes typically has min pairwise
# cosine sim well above 0.5 and mean above 0.7. A gallery contaminated by a
# second person via a tracker swap pulls min toward 0 (cross-cluster pairs)
# and mean below ~0.55. The gate sits below the clean band so brief sensor
# noise doesn't flake it, and well above the contaminated band so a real swap
# is caught.
REID_PAIR_MIN = 0.45
REID_PAIR_MEAN = 0.65
