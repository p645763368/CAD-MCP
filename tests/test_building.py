import unittest,math,asyncio
from dataclasses import dataclass
from engineering import building as g
from engineering.building_checks import check_snapshot
from building_units import UnitBackend,scale_payload,scale_input
from engineering.arch import model
from building_tools import token


def snap(rows=None,units=4):return {'token':'state','units':units,'rows':rows or [],'layers':[{'name':'0','used':True},{'name':'UNUSED','used':False}], 'fonts':[],'xrefs':[],'layouts':[],'complete':True,'errors':[]}
def line(h,a,b,layer='A-WALL'):return {'handle':h,'type':'LINE','space':'model','space_units':4,'points':[a,b],'length':math.dist(a,b),'layer':layer,'locked':False,'record':None,'arch_values':[]}
class BuildingGeometry(unittest.TestCase):
 def test_grid_units_rotation_labels(self):
  p=g.grid_plan([0,6],[0,8],[],None,[10,20],90,1500,50,'both',1000,'G',{'axis':'AX','label':'TXT'})
  self.assertEqual(len(p['result']['axes']),4);self.assertEqual(len(p['entities']),20)
  self.assertEqual(p['entities'][1]['radius'],.25)
  self.assertAlmostEqual(p['entities'][0]['start'][0],11.5)
 def test_arc_single_end(self):
  p=g.grid_plan([],[],[dict(center=[0,0],radius=10,start_angle_deg=0,end_angle_deg=90,label='R1')],None,[0,0],0,300,50,'end',1000,'G',{'axis':'AX','label':'TXT'})
  self.assertEqual(len(p['entities']),4);self.assertEqual(p['entities'][-1]['record']['side'],'end')
 def test_grid_duplicate_labels_refused(self):
  with self.assertRaises(ValueError):g.grid_plan([0],[0],[],{'x':['A'],'y':['A']},[0,0],0,500,50,'both',1,'G',{'axis':'A','label':'B'})
 def parking(self,**kw):
  spec=dict(origin=[0,0],count=3,width_mm=2500,length_mm=5000,aisle_mm=6000,angle_deg=90,sides='single',prefix='P');spec.update(kw)
  return g.parking_plan([spec],None,[],1000,'P',0,'P','T',200)
 def test_parking_physical_width_and_count(self):
  p=self.parking();self.assertEqual(p['result']['count'],3);self.assertAlmostEqual(g.ring(p['result']['bays'][0]['points']).area,12.5)
 def test_parking_double_row_unique(self):
  p=self.parking(sides='double');self.assertEqual(p['result']['count'],6);self.assertEqual(len({r['label'] for r in p['result']['bays']}),6)
 def test_angled_parking_net_width(self):
  p=self.parking(angle_deg=60);self.assertEqual(p['result']['count'],3);self.assertAlmostEqual(g.ring(p['result']['bays'][0]['points']).area,12.5)
 def test_parallel_parking(self):self.assertEqual(self.parking(angle_deg=0)['result']['count'],3)
 def test_parking_obstacle_and_boundary(self):
  spec=dict(origin=[0,0],count=3,width_mm=2500,length_mm=5000,aisle_mm=6000)
  p=g.parking_plan([spec],[[-1,-4],[6,-4],[6,9],[-1,9]],[[[0,4],[1,4],[1,5],[0,5]]],1000,'P',0,'P','T',200)
  self.assertEqual(p['result']['count'],1);self.assertEqual(len(p['result']['omitted']),2)
 def test_special_bay_width_and_access(self):
  p=self.parking(count=1,bay_overrides={'0':{'width_mm':3500,'access_strip_mm':1200,'kind':'accessible'}});self.assertEqual(p['result']['bays'][0]['width_mm'],3500);self.assertEqual(len(p['entities']),3)
 def test_parking_aisle_conflict_between_rows(self):
  specs=[dict(origin=[0,0],count=1,width_mm=2500,length_mm=5000,aisle_mm=6000,prefix='A'),dict(origin=[0,5],count=1,width_mm=2500,length_mm=5000,aisle_mm=6000,prefix='B')]
  p=g.parking_plan(specs,None,[],1000,'P',0,'P','T',200);self.assertEqual(p['result']['count'],1)
 def test_area_union_deductions(self):
  z=[dict(id='a',floor='1',rule='full',boundary=[[0,0],[10,0],[10,10],[0,10]],deductions=[[[1,1],[3,1],[3,3],[1,3]],[[2,2],[4,2],[4,4],[2,4]]])]
  r=g.area_rows(z,{'full':dict(factor=1,basis='project',version='1')},1000);self.assertAlmostEqual(r['total_m2'],93)
 def test_multiple_area_types_not_summed(self):
  zones=[dict(id=t,area_type=t,floor='1',rule='r',boundary=[[0,0],[10,0],[10,10],[0,10]]) for t in ['building','far']]
  r=g.area_rows(zones,{'r':dict(factor=1,basis='project',version='1')},1000);self.assertIsNone(r['total_m2']);self.assertEqual(r['totals_by_type_m2'],{'building':100,'far':100})
 def test_area_overlap_refused(self):
  zones=[dict(id=t,floor='1',rule='r',boundary=[[0,0],[10,0],[10,10],[0,10]]) for t in ['a','b']]
  with self.assertRaises(ValueError):g.area_rows(zones,{'r':dict(factor=1,basis='project',version='1')},1000)
 def test_area_outside_deduction_refused(self):
  zones=[dict(id='a',floor='1',rule='r',boundary=[[0,0],[1,0],[1,1],[0,1]],deductions=[[[1,1],[3,1],[3,3],[1,3]]])]
  with self.assertRaises(ValueError):g.area_rows(zones,{'r':dict(factor=1,basis='project',version='1')},1)
 def test_columns_metres(self):
  p=g.columns_plan([[1,2]],600,400,'rectangle',0,1000,'C','A');self.assertAlmostEqual(g.ring(p['entities'][0]['points']).area,.24)
 def test_beam_width(self):
  p=g.beams_plan([[[0,0],[6,0]]],300,1000,'B','A');self.assertAlmostEqual(g.ring(p['entities'][0]['points']).area,1.8)
 def test_wall_corner(self):
  p=g.wall_join_plan([line('1',[0,0,0],[5,0,0]),line('2',[6,1,0],[6,5,0])],[],'corner',[1,0],2000,1000,'J');self.assertEqual(p['result']['corner'],[6,0,0])
 def test_wall_column_clipping(self):
  col={'handle':'C','type':'LWPOLYLINE','closed':True,'bulges':[0]*4,'points':[[4,-1,0],[6,-1,0],[6,1,0],[4,1,0]]}
  p=g.wall_join_plan([line('1',[0,0,0],[10,0,0])],[col],'columns',[],3000,1000,'J');self.assertEqual(len(p['entities']),2);self.assertTrue(p['updates'][0]['delete'])
 def test_ramp_slope_and_limit(self):
  p=g.ramp_plan([[0,0],[10,0]],1200,[0,800],[],1000,'R','A',.08);self.assertAlmostEqual(p['result']['segments'][0]['slope'],.08)
  with self.assertRaises(ValueError):g.ramp_plan([[0,0],[10,0]],1200,[0,900],[],1000,'R','A',.08)
 def test_stair_headroom_worst_point(self):
  r=g.stair_check(10,150,300,1200,{'headroom_mm':{'min':2100}},[[0,0],[3000,1500]],[dict(id='B',start_mm=1000,end_mm=2000,underside_mm=3000)])
  self.assertFalse(r['passed']);self.assertEqual(r['clearances'][0]['clearance_mm'],2000);self.assertTrue(r['headroom_complete'])
 def test_stair_vertical_profile(self):
  r=g.stair_check(2,150,300,1200,{'headroom_mm':{'min':2100}},[[0,0],[0,150],[300,150],[300,300],[600,300]],[dict(start_mm=0,end_mm=600,underside_mm=2500)]);self.assertEqual(r['clearances'][0]['clearance_mm'],2200)
 def test_headroom_missing_is_incomplete(self):self.assertFalse(g.stair_check(10,150,300,1200,{'width_mm':{'min':1000}},None,[])['headroom_complete'])
 def test_plan_token_binds_geometry(self):
  self.assertNotEqual(token({'token':'doc1'},{'x':1}),token({'token':'doc1'},{'x':2}));self.assertNotEqual(token({'token':'doc1'},{}),token({'token':'doc2'},{}))

class BuildingChecks(unittest.TestCase):
 def test_empty_layer_does_not_fail_execution(self):
  r=check_snapshot(snap(),['empty_layers']);self.assertTrue(r['ok']);self.assertTrue(r['passed']);self.assertEqual(r['summary']['info'],1)
 def test_real_zero_length_and_3d(self):
  r=check_snapshot(snap([line('1',[0,0,0],[0,0,0]),line('2',[0,0,0],[0,0,10])]),['zero_length']);self.assertTrue(r['ok']);self.assertFalse(r['passed']);self.assertEqual(len(r['findings']),1)
 def test_reversed_duplicate(self):
  r=check_snapshot(snap([line('1',[0,0,0],[1,0,0]),line('2',[1,0,0],[0,0,0])]),['duplicate_entities']);self.assertEqual(len(r['findings']),1)
 def test_layer_difference_kept(self):
  r=check_snapshot(snap([line('1',[0,0,0],[1,0,0]),line('2',[1,0,0],[0,0,0],'B')]),['duplicate_entities']);self.assertFalse(r['findings'])
 def test_closed_polyline_rotated_vertex_duplicate(self):
  a={'handle':'1','type':'LWPOLYLINE','space':'model','layer':'A','closed':True,'points':[[0,0,0],[1,0,0],[1,1,0]],'bulges':[0,0,0]};b=dict(a,handle='2',points=a['points'][1:]+a['points'][:1]);r=check_snapshot(snap([a,b]),['duplicate_entities']);self.assertEqual(len(r['findings']),1)
 def test_incomplete_snapshot_is_not_pass(self):
  r=snap();r.update(complete=False,errors=['unreadable']);result=check_snapshot(r);self.assertFalse(result['ok']);self.assertFalse(result['complete'])
 def test_unknown_check_rejected(self):
  with self.assertRaises(ValueError):check_snapshot(snap(),['something'])
 def test_asset_missing(self):
  s=snap();s['xrefs']=[dict(name='base',path='base.dwg',status='Unresolved')];r=check_snapshot(s,['assets']);self.assertFalse(r['passed'])

class Units(unittest.IsolatedAsyncioTestCase):
 def test_payload_migration(self):
  p=model.to_payload(model.Wall('W',((0,0),(5,0)),.2));q=scale_payload(p,1000);self.assertEqual(q['axis'],[[0,0],[5000,0]]);self.assertEqual(q['thickness'],200)
 def test_input_coordinates_and_physical_width(self):
  x=scale_input('arch_wall',{'walls':[dict(id='W',axis=[[0,0],[5,0]],thickness=200)]},1000);self.assertEqual(x['walls'][0]['axis'][1],[5000,0]);self.assertEqual(x['walls'][0]['thickness'],200)
 async def test_proxy_scales_geometry(self):
  class Fake:
   async def entity_create_line(self,x1,y1,x2,y2,layer=None):return (x1,y1,x2,y2)
  result=await UnitBackend(Fake(),1000).entity_create_line(0,0,5000,0);self.assertEqual(result,(0,0,5,0))
 async def test_proxy_writes_unit_tag(self):
  class Fake:
   async def entity_set_xdata(self,handle,app_name,values):return model.decode(values)
  p=model.to_payload(model.Wall('W',((0,0),(5000,0)),200));r=await UnitBackend(Fake(),1000).entity_set_xdata('1',model.APP_ID,model.to_values(p));self.assertEqual(r['coordinate_units'],'mm');self.assertEqual(r['model_mm_per_unit'],1000);self.assertEqual(model.from_payload(r).thickness,200)
 async def test_proxy_refuses_untagged_metre_record(self):
  p=model.to_payload(model.Wall('W',((0,0),(5000,0)),200))
  class Fake:
   async def entity_get_xdata(self,handle,app_name):return {'xdata':{app_name:model.to_values(p)}}
  with self.assertRaises(ValueError):await UnitBackend(Fake(),1000).entity_get_xdata('1',model.APP_ID)

class AddedBranches(unittest.TestCase):
 def test_architectural_preflight(self):
  from engineering.preflight import preflight_drawing
  r=preflight_drawing('建筑平面',requirements={'units':'m','scope':'model'})
  self.assertTrue(r.ready);self.assertEqual(r.normalized_spec['layer_set_id'],'arch')
 def test_dimension_text_position_scaling(self):
  from building_units import transform_properties
  self.assertEqual(transform_properties({'text_position':[1,2,0]},1000)['text_position'],[1000,2000,0])
 def test_headroom_requirement_without_profile_not_passed(self):
  r=g.stair_check(10,150,300,1200,{'headroom_mm':{'min':2100}},None,[])
  self.assertFalse(r['passed']);self.assertFalse(r['complete'])
 def test_unknown_stair_rule_refused(self):
  with self.assertRaises(ValueError):g.stair_check(10,150,300,1200,{'headrooom':{'min':2100}},None,[])
 def test_empty_ramp_landing_refused(self):
  with self.assertRaises(ValueError):g.ramp_plan([[0,0],[10,0]],1200,[0,800],[{'boundary':[[20,20],[21,20],[21,21]],'elevation_mm':800}],1000,'R','A')
 def test_circle_column_exact_intersection(self):
  col={'handle':'C','type':'CIRCLE','center':[5,.5,0],'radius':1}
  p=g.wall_join_plan([line('L',[0,0,0],[10,0,0])],[col],'columns',[],3000,1000,'J')
  self.assertAlmostEqual(p['entities'][0]['end'][0],5-math.sqrt(.75),places=10)
 def test_closed_beam_clipping(self):
  beam=g.beams_plan([[[0,0],[6,0]]],300,1000,'B','A')['entities'][0]
  r={'handle':'B','type':'LWPOLYLINE','points':beam['points'],'closed':True,'bulges':[0]*4,'layer':'A','locked':False,'record':beam['record']}
  col={'handle':'C','type':'LWPOLYLINE','closed':True,'points':[[2.7,-.3,0],[3.3,-.3,0],[3.3,.3,0],[2.7,.3,0]],'bulges':[0]*4}
  p=g.wall_join_plan([r],[col],'columns',[],1000,1000,'J');self.assertEqual(len(p['entities']),2)
 def test_parking_numbers_continuous_after_filter(self):
  spec=dict(origin=[0,0],count=3,width_mm=2500,length_mm=5000,aisle_mm=6000)
  p=g.parking_plan([spec],None,[[[0,4],[1,4],[1,5],[0,5]]],1000,'P',0,'P','T',200)
  self.assertEqual([x['label'] for x in p['result']['bays']],['P1','P2'])
 def test_type_tags_are_allowed_for_matching_specs(self):
  r1={'handle':'1','type':'INSERT','space':'model','layer':'D','record':{'kind':'door_window','group':'D','tag':'M1','numbering':'type','source_values':{'width':900,'height':2100}}}
  r2=dict(r1,handle='2');r=check_snapshot(snap([r1,r2]),['duplicate_tags']);self.assertTrue(r['passed'])
 def test_type_tag_conflict_detected(self):
  r1={'handle':'1','type':'INSERT','space':'model','layer':'D','record':{'kind':'door_window','group':'D','tag':'M1','numbering':'type','source_values':{'width':900}}}
  r2=dict(r1,handle='2',record=dict(r1['record'],source_values={'width':1000}));self.assertFalse(check_snapshot(snap([r1,r2]),['duplicate_tags'])['passed'])
 def test_table_internal_zero_not_a_drawing_error(self):
  r=line('1',[0,0,0],[0,0,0]);r['space']='block:*T1'
  self.assertTrue(check_snapshot(snap([r]),['zero_length'])['passed'])
 def test_public_output_names(self):
  from building_delivery import safe_name
  self.assertEqual(safe_name('01.平面图'),'01.平面图')
  for name in ['../x','CON','test.','a/b','a\\b','x:y']:
   with self.assertRaises(ValueError):safe_name(name)

if __name__=='__main__':unittest.main()
