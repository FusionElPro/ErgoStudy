<<<<<<< HEAD
import math
import unittest

from modules.fatigue import calculate_ear, calculate_mar


class Vector:
    def __init__(self, values):
        self.values = values

    def __sub__(self, other):
        return Vector(tuple(left - right for left, right in zip(self.values, other.values)))


class LinearAlgebra:
    @staticmethod
    def norm(vector):
        return math.sqrt(sum(value * value for value in vector.values))


class NumpyStub:
    linalg = LinearAlgebra()

    @staticmethod
    def asarray(values):
        return Vector(values)


class Landmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class FatigueMetricTests(unittest.TestCase):
    def test_eye_aspect_ratio_uses_vertical_to_horizontal_distances(self):
        points = [
            Landmark(0, 0),
            Landmark(1, 1),
            Landmark(3, 1),
            Landmark(4, 0),
            Landmark(3, -1),
            Landmark(1, -1),
        ]

        self.assertAlmostEqual(calculate_ear(NumpyStub, points, (0, 1, 2, 3, 4, 5)), 0.5)

    def test_mouth_aspect_ratio_uses_lip_gap_and_mouth_width(self):
        points = [Landmark(0, 0) for _ in range(309)]
        points[13] = Landmark(0, 1)
        points[14] = Landmark(0, 0)
        points[78] = Landmark(-2, 0)
        points[308] = Landmark(2, 0)

        self.assertAlmostEqual(calculate_mar(NumpyStub, points), 0.25)


if __name__ == "__main__":
    unittest.main()
=======
import math
import unittest

from modules.fatigue import calculate_ear, calculate_mar


class Vector:
    def __init__(self, values):
        self.values = values

    def __sub__(self, other):
        return Vector(tuple(left - right for left, right in zip(self.values, other.values)))


class LinearAlgebra:
    @staticmethod
    def norm(vector):
        return math.sqrt(sum(value * value for value in vector.values))


class NumpyStub:
    linalg = LinearAlgebra()

    @staticmethod
    def asarray(values):
        return Vector(values)


class Landmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class FatigueMetricTests(unittest.TestCase):
    def test_eye_aspect_ratio_uses_vertical_to_horizontal_distances(self):
        points = [
            Landmark(0, 0),
            Landmark(1, 1),
            Landmark(3, 1),
            Landmark(4, 0),
            Landmark(3, -1),
            Landmark(1, -1),
        ]

        self.assertAlmostEqual(calculate_ear(NumpyStub, points, (0, 1, 2, 3, 4, 5)), 0.5)

    def test_mouth_aspect_ratio_uses_lip_gap_and_mouth_width(self):
        points = [Landmark(0, 0) for _ in range(309)]
        points[13] = Landmark(0, 1)
        points[14] = Landmark(0, 0)
        points[78] = Landmark(-2, 0)
        points[308] = Landmark(2, 0)

        self.assertAlmostEqual(calculate_mar(NumpyStub, points), 0.25)


if __name__ == "__main__":
    unittest.main()
>>>>>>> origin/main
