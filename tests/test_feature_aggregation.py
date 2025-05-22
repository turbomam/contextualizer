#!/usr/bin/env python3
"""
Test for the feature_aggregation module.

This test ensures that the feature_aggregation module can be imported correctly
from its new location in the src/utils directory.
"""

import unittest
import os
import sys

# Add the project root directory to the Python path if needed
# This ensures the test can run both with unittest and pytest
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.feature_aggregation import analyze_feature_density, FeatureAggregation

class TestFeatureAggregation(unittest.TestCase):
    """Test case for feature_aggregation module."""
    
    def test_module_import(self):
        """Test that the module can be imported correctly."""
        # If the import succeeds, the test passes
        self.assertTrue(hasattr(analyze_feature_density, '__call__'))
        self.assertTrue(FeatureAggregation is not None)
    
    def test_basic_functionality(self):
        """Test basic functionality with dummy data."""
        # Create dummy features for testing
        features = [
            {
                "feature_id": "test1",
                "feature_type": "natural:tree",
                "distance_from_center": 50,
                "tags": {"natural": "tree"}
            },
            {
                "feature_id": "test2",
                "feature_type": "natural:tree",
                "distance_from_center": 80,
                "tags": {"natural": "tree"}
            },
            {
                "feature_id": "test3",
                "feature_type": "natural:tree",
                "distance_from_center": 120,
                "tags": {"natural": "tree"}
            }
        ]
        
        # Test with only a few trees (not enough to trigger the forest inference)
        result = analyze_feature_density(features)
        # The analysis might not yield any inferences with this small sample,
        # but it should run without errors
        self.assertIsInstance(result, list)

if __name__ == '__main__':
    unittest.main()