import unittest
from collections import defaultdict, deque
from contact_tracing import Tracker
from tracker_config import config

class TestTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker()
        
    def test_contact_history(self):
        # Test that contact history is properly maintained
        person_id = "test1"
        contact_info = {'person': 'test2', 'position': (1,1), 'time': 12345}
        
        # Add more contacts than max history
        for i in range(config['max_history'] + 10):
            self.tracker.update_contact_history(person_id, contact_info)
            
        # Should only keep max_history items
        self.assertEqual(len(self.tracker.contact_history[person_id]), config['max_history'])
        
    def test_position_check(self):
        # Test that contacts are detected
        self.tracker.positions = {
            'person1': (1,1),
            'person2': (1,1),
            'person3': (2,2)
        }
        
        self.tracker.check_contacts('person1', 1, 1)
        
        # Should have recorded contacts between person1 and person2
        self.assertEqual(len(self.tracker.contact_history['person1']), 1)
        self.assertEqual(len(self.tracker.contact_history['person2']), 1)
        self.assertEqual(len(self.tracker.contact_history.get('person3', [])), 0)

if __name__ == '__main__':
    unittest.main()