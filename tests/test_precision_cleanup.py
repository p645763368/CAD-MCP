import unittest,copy,math
from engineering.precision_cleanup import plan,bounds

def row(h,points,closed=False,**kw):
    points=[list(p) if len(p)==3 else [*p,0.] for p in points]
    return dict(handle=h,points=points,closed=closed,bbox=bounds(points),**kw)

class GeometryCleanup(unittest.TestCase):
    def test_shared_corner_and_true_lengths(self):
        rows=[row('A',[(0,0),(2999.997,0)]),row('B',[(2999.997,0),(2999.997,4000.002)])]
        old=copy.deepcopy(rows);r=plan(rows,['A','B'],1,.01,[0,0])
        self.assertTrue(r['can_apply']);self.assertEqual(r['changes'][0]['lengths_after'],[3000]);self.assertEqual(r['changes'][1]['lengths_after'],[4000]);self.assertEqual(rows,old)
    def test_unselected_connected_line_blocks(self):
        rows=[row('A',[(0,0),(2999.997,0)]),row('B',[(2999.997,0),(2999.997,4000)])]
        self.assertFalse(plan(rows,['A'],1,.01,[0,0])['can_apply'])
    def test_t_junction_blocks_when_host_moves(self):
        rows=[row('A',[(0,.003),(3000,.003)]),row('B',[(1500,.003),(1500,1000)])]
        self.assertFalse(plan(rows,['A'],1,.01,[0,0])['can_apply'])
    def test_new_contact_blocks(self):
        rows=[row('A',[(0,.003),(3000,.003)]),row('B',[(1500,0),(1500,-100)])]
        self.assertFalse(plan(rows,['A'],1,.01,[0,0])['can_apply'])
    def test_closed_polyline_preserves_z(self):
        r=plan([row('A',[(.003,.002,7),(3000.002,.002,7),(3000.002,2000.001,7),(.003,2000.001,7)],True)],['A'],1,.01,[0,0])
        self.assertTrue(r['can_apply']);self.assertEqual([p[2] for p in r['changes'][0]['after']],[7]*4)
    def test_metre_equivalent(self):
        r=plan([row('A',[(0,0),(2.999997,0)])],['A'],.001,.00001,[0,0]);self.assertTrue(r['can_apply']);self.assertEqual(r['changes'][0]['lengths_after'],[3])
    def test_origin_offset(self):
        r=plan([row('A',[(100.253,200.25),(400.247,200.25)])],['A'],1,.01,[100.25,200.25]);self.assertEqual(r['changes'][0]['lengths_after'],[300])
    def test_limit_refuses_all(self):
        r=plan([row('A',[(0,0),(3000.2,0)])],['A'],1,.01,[0,0]);self.assertFalse(r['can_apply'])
    def test_degenerate_rejected(self):
        r=plan([row('A',[(0,0),(.003,0)])],['A'],1,.01,[0,0]);self.assertFalse(r['can_apply'])
    def test_diagonal_skipped(self):
        r=plan([row('A',[(.003,0),(100.003,100)])],['A'],1,.01,[0,0]);self.assertEqual(len(r['skipped']),1)
    def test_nearby_unsupported_blocks(self):
        rows=[row('A',[(0,0),(3000.003,0)]),dict(handle='B',bbox=[2000,-10,4000,10],unsupported='block')]
        self.assertFalse(plan(rows,['A'],1,.01,[0,0])['can_apply'])
    def test_unknown_bbox_blocks(self):
        r=plan([row('A',[(0,0),(3000.003,0)]),dict(handle='B',unsupported='proxy')],['A'],1,.01,[0,0]);self.assertFalse(r['can_apply'])
    def test_idempotent_geometry(self):
        rows=[row('A',[(0,0),(3000,0)])];r=plan(rows,['A'],1,.01,[0,0]);self.assertEqual(r['changed_count'],0)
    def test_invalid_numbers(self):
        for step,move in [(float('nan'),.01),(1,float('inf')),(1,.6),(0,.01)]:
            with self.assertRaises(ValueError):plan([],[],step,move,[0,0])
    def test_disconnected_same_grid_merge_blocked(self):
        rows=[row('A',[(0,0),(3000.003,0)]),row('B',[(3000.004,0),(4000,0)])]
        self.assertFalse(plan(rows,['A','B'],1,.01,[0,0])['can_apply'])
    def test_overlapping_line_keeps_relationship(self):
        rows=[row('A',[(0,0),(3000.003,0)]),row('B',[(1000,0),(2000,0)])]
        self.assertTrue(plan(rows,['A'],1,.01,[0,0])['can_apply'])

if __name__=='__main__':unittest.main()
