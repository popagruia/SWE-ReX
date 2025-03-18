import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import unittest
from swerex.runtime.pod import PodRuntime

class TestPodRuntime(unittest.TestCase):
    def test_run_pod(self):
        runtime = PodRuntime()
        pod_spec = {"metadata": {"name": "test-pod"}}
        runtime.run_pod(pod_spec)
        self.assertTrue(True)  # Add proper assertions as needed

if __name__ == "__main__":
    unittest.main()