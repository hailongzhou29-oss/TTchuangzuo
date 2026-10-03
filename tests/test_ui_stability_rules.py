"""Migration and source applicability regressions from the consolidated UI spec."""
import copy
import unittest
from app.core.script_settings import migrate,active_settings,carrier_fields

class StabilityRulesTests(unittest.TestCase):
    def test_life_synonym_preserves_original(self):
        original={'kind':'script','advanced':{'叙事对象':'人物一生'}}
        state=migrate(original)['script_settings']
        self.assertEqual(state['values']['subject'],'subject.01')
        self.assertEqual(state['migration_original'],original)
    def test_repair_known_pending_keeps_explicit_different_choice(self):
        state=migrate({'advanced':{'叙事对象':'人物一生'}})['script_settings']
        state['values']['subject']='subject.02'; item=dict(source='advanced.叙事对象',value='人物一生'); state['unresolved']=[item]
        repaired=migrate(dict(script_settings=state))['script_settings']
        self.assertEqual(repaired['values']['subject'],'subject.02'); self.assertEqual(repaired['unresolved'],[item])
    def test_public_and_screen_do_not_activate_device_position(self):
        for carrier in ['carrier.06','carrier.07','carrier.01']:
            c=migrate({'duration':180},new=True); c['script_settings']['values'].update(carrier=carrier,position='旧位置不能误发')
            self.assertNotIn('position',carrier_fields(c['script_settings']['values']))
            self.assertNotIn('position',active_settings(c)['explicit'])
    def test_normal_carrier_detail_remains_selectable(self):
        c=migrate({'duration':180},new=True); c['script_settings']['values'].update(carrier='carrier.01',carrier_item='carrier.01.1')
        self.assertEqual(active_settings(c)['explicit']['carrier_item'],'carrier.01.1')
    def test_retained_migration_text_is_not_commerce_only(self):
        c=migrate({'duration':180},new=True); c['script_settings']['values']['retained_requirements']='旧要求：保留角色手改'
        self.assertEqual(active_settings(c)['explicit']['retained_requirements'],'旧要求：保留角色手改')

if __name__=='__main__': unittest.main()
