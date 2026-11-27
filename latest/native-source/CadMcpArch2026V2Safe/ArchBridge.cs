using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.EditorInput;
using AcApp=Autodesk.AutoCAD.ApplicationServices.Core.Application;
using System.Text.Json;
namespace CadMcpArchV2;
public partial class Bridge {
 [LispFunction("MCPARCH2026V2SAFE")]
 public static ResultBuffer Run(ResultBuffer args) {
  object result;
  try {
   var a=JsonDocument.Parse((string)args.AsArray()[0].Value).RootElement;var op=S(a,"op");
   if(op=="ping")result=new {ok=true,version="2.0.2"};
   else {
    var doc=AcApp.DocumentManager.MdiActiveDocument??throw new InvalidOperationException("No document");
    if(!string.Equals(doc.Name,S(a,"document"),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Active document changed");
    using var l=doc.LockDocument();using var tr=doc.Database.TransactionManager.StartTransaction();var db=doc.Database;
    result=op switch {"polyline_edit"=>PolylineEdit(a,db,tr),"curve_split"=>Split(a,db,tr),"curve_join"=>Join(a,db,tr),"entity_stretch"=>Stretch(a,db,tr),"selection_polygon_exact"=>Select(a,db,tr,doc.Editor),"layer_rename"=>Rename(a,db,tr),"layer_merge"=>Merge(a,db,tr),"entity_modify_where"=>ModifyAdvanced(a,db,tr),"dimension_edit"=>DimEdit(a,db,tr),"dimension_arrange"=>DimArrange(a,db,tr),"entity_draw_order"=>OrderAdvanced(a,db,tr),"arch_company_profile"=>Profile(a,db,tr),"curve_trim"=>TrimCurve(a,db,tr),"curve_extend"=>ExtendCurve(a,db,tr),"stretch_window"=>StretchWindow(a,db,tr),"entity_match_properties"=>MatchProperties(a,db,tr),"dimension_chain"=>DimChain(a,db,tr),"annotation_scales"=>AnnotationScales(a,db,tr),"arch_profile_config"=>ProfileConfig(a,db,tr),"drawing_import_standards"=>ImportStandards(a,db,tr),_=>throw new ArgumentException("Unknown operation")};
    if(JsonSerializer.Serialize(result).Length>7000)throw new ArgumentException("Result too large; use smaller batch (transaction rolled back)");
    tr.Commit();doc.Editor.Regen();
   }
  } catch(System.Exception e){result=new {ok=false,error=e.Message};}
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(result)));
 }
 static string S(JsonElement a,string k,string fallback="")=>a.TryGetProperty(k,out var v)&&v.ValueKind!=JsonValueKind.Null?v.GetString()??fallback:fallback;
 static bool Has(JsonElement a,string k)=>a.TryGetProperty(k,out var v)&&v.ValueKind!=JsonValueKind.Null;
 static bool B(JsonElement a,string k,bool d=false)=>Has(a,k)?a.GetProperty(k).GetBoolean():d;
 static double N(JsonElement a,string k,double d=0){double x=Has(a,k)?a.GetProperty(k).GetDouble():d;if(!double.IsFinite(x))throw new ArgumentException("Finite number required: "+k);return x;}
 static Point3d P(JsonElement v){var x=v.EnumerateArray().Select(z=>z.GetDouble()).ToArray();if(x.Length<2||x.Length>3||x.Any(z=>!double.IsFinite(z)))throw new ArgumentException("Finite XY/XYZ point required");return new(x[0],x[1],x.Length==3?x[2]:0);}
 static double[] XYZ(Point3d p)=>new[]{p.X,p.Y,p.Z};
 static ObjectId Id(Database db,string h)=>db.GetObjectId(false,new Handle(Convert.ToInt64(h,16)),0);
 static ObjectId Space(Database db)=>db.TileMode||Convert.ToInt32(AcApp.GetSystemVariable("CVPORT"))!=1?SymbolUtilityServices.GetBlockModelSpaceId(db):SymbolUtilityServices.GetBlockPaperSpaceId(db);
 static Entity E(Database db,Transaction tr,string h,bool write=true) {
  var e=tr.GetObject(Id(db,h),OpenMode.ForRead) as Entity??throw new ArgumentException("Handle is not an entity");
  if(e.OwnerId!=Space(db))throw new ArgumentException("Entity is not in active drawing space");
  if(write){var layer=(LayerTableRecord)tr.GetObject(e.LayerId,OpenMode.ForRead);if(layer.IsLocked)throw new ArgumentException("Locked source layer: "+layer.Name);e.UpgradeOpen();}return e;
 }
 static List<string> Handles(JsonElement a){var h=a.GetProperty("handles").EnumerateArray().Select(x=>x.GetString()!).ToList();if(h.Count==0||h.Count>100||h.Distinct(StringComparer.OrdinalIgnoreCase).Count()!=h.Count)throw new ArgumentException("1..100 distinct handles required");return h;}
 static object PolylineEdit(JsonElement a,Database db,Transaction tr){
  var p=E(db,tr,S(a,"handle")) as Polyline??throw new ArgumentException("LWPOLYLINE only");
  if(!p.Normal.IsEqualTo(Vector3d.ZAxis,new Tolerance(1e-9,1e-9)))throw new ArgumentException("Only +Z XY polylines supported");
  foreach(var edit in a.GetProperty("edits").EnumerateArray()) {
   int i=edit.GetProperty("index").GetInt32();string action=S(edit,"action","set");
   if(action=="remove"){if(i<0||i>=p.NumberOfVertices)throw new ArgumentException("Invalid vertex index");p.RemoveVertexAt(i);}
   else if(action=="insert") {if(i<0||i>p.NumberOfVertices)throw new ArgumentException("Invalid vertex index");var q=P(edit.GetProperty("point"));if(Math.Abs(q.Z-p.Elevation)>1e-8)throw new ArgumentException("Point Z must equal elevation");p.AddVertexAt(i,new(q.X,q.Y),N(edit,"bulge"),N(edit,"start_width"),N(edit,"end_width"));}
   else if(action=="set") {if(i<0||i>=p.NumberOfVertices)throw new ArgumentException("Invalid vertex index");if(Has(edit,"point")){var q=P(edit.GetProperty("point"));if(Math.Abs(q.Z-p.Elevation)>1e-8)throw new ArgumentException("Point Z must equal elevation");p.SetPointAt(i,new(q.X,q.Y));}if(Has(edit,"bulge"))p.SetBulgeAt(i,N(edit,"bulge"));if(Has(edit,"start_width"))p.SetStartWidthAt(i,N(edit,"start_width"));if(Has(edit,"end_width"))p.SetEndWidthAt(i,N(edit,"end_width"));}
   else throw new ArgumentException("action: set/insert/remove");
  }
  if(Has(a,"closed"))p.Closed=B(a,"closed");
  if(p.NumberOfVertices<(p.Closed?3:2))throw new ArgumentException("Too few vertices");
  for(int i=0;i<p.NumberOfVertices-(p.Closed?0:1);i++)if(p.GetPoint3dAt(i).DistanceTo(p.GetPoint3dAt((i+1)%p.NumberOfVertices))<1e-8)throw new ArgumentException("Zero length segment");
  return new {ok=true,handle=p.Handle.ToString(),vertices=p.NumberOfVertices,closed=p.Closed,length=p.Length,area=p.Closed?(double?)p.Area:null};
 }
 static void SupportedCurve(Curve c){if(c is not Line && c is not Arc && c is not Polyline && c is not Circle)throw new ArgumentException("LINE/ARC/CIRCLE/LWPOLYLINE only");}
 static object Split(JsonElement a,Database db,Transaction tr){
  var c=E(db,tr,S(a,"handle")) as Curve??throw new ArgumentException("Curve required");SupportedCurve(c);var pts=new Point3dCollection();
  foreach(var v in a.GetProperty("points").EnumerateArray()){var p=P(v);if(c.GetClosestPointTo(p,false).DistanceTo(p)>1e-7)throw new ArgumentException("Split point must lie on curve");pts.Add(p);}
  if(pts.Count<1||pts.Count>20)throw new ArgumentException("1..20 split points required");
  using var pieces=c.GetSplitCurves(pts);if(pieces.Count<2)throw new ArgumentException("No actual split");
  var owner=(BlockTableRecord)tr.GetObject(c.OwnerId,OpenMode.ForWrite);var hs=new List<string>();double length=0;
  foreach(DBObject o in pieces){if(o is not Curve part)throw new ArgumentException("Unexpected split output");part.SetPropertiesFrom(c);var id=owner.AppendEntity(part);tr.AddNewlyCreatedDBObject(part,true);hs.Add(id.Handle.ToString());length+=part.GetDistanceAtParameter(part.EndParam)-part.GetDistanceAtParameter(part.StartParam);}
  double original=c.GetDistanceAtParameter(c.EndParam)-c.GetDistanceAtParameter(c.StartParam);if(Math.Abs(length-original)>Math.Max(1e-7,original*1e-9))throw new ArgumentException("Length preservation check failed");
  bool erase=B(a,"replace",true);if(erase)c.Erase();return new {ok=true,source=S(a,"handle"),source_erased=erase,handles=hs,length};
 }
 static object Join(JsonElement a,Database db,Transaction tr){
  var hs=Handles(a);if(hs.Count<2)throw new ArgumentException("At least two curves required");var cs=hs.Select(h=>E(db,tr,h) as Curve??throw new ArgumentException("Curve required")).ToArray();
  foreach(var c in cs){SupportedCurve(c);if(c.Closed)throw new ArgumentException("Open curves only");}
  var joined=cs[0].JoinEntities(cs.Skip(1).Cast<Entity>().ToArray());if(joined.Count!=cs.Length-1)throw new ArgumentException("Not all curves can join; rolled back. Select a polyline first for mixed LINE/ARC joins");
  foreach(var c in cs.Skip(1))c.Erase();return new {ok=true,handle=hs[0],erased=hs.Skip(1).ToArray()};
 }
 static object Stretch(JsonElement a,Database db,Transaction tr){
  var delta=P(a.GetProperty("offset"))-Point3d.Origin;var items=a.GetProperty("items").EnumerateArray().ToArray();if(items.Length<1||items.Length>100)throw new ArgumentException("1..100 items required");var output=new List<object>();var seen=new HashSet<ObjectId>();
  foreach(var item in items){var e=E(db,tr,S(item,"handle"));if(!seen.Add(e.ObjectId))throw new ArgumentException("Duplicate handle");if(e is not Line && e is not Polyline)throw new ArgumentException("Only LINE/LWPOLYLINE stretch supported");var indices=item.GetProperty("indices").EnumerateArray().Select(x=>x.GetInt32()).ToArray();if(indices.Length==0||indices.Distinct().Count()!=indices.Length)throw new ArgumentException("Distinct nonempty indices required");
   if(e is Line line){foreach(int i in indices){if(i==0)line.StartPoint+=delta;else if(i==1)line.EndPoint+=delta;else throw new ArgumentException("LINE indices are 0,1");}if(line.Length<1e-8)throw new ArgumentException("Zero-length result");}
   else if(e is Polyline p){if(!p.Normal.IsEqualTo(Vector3d.ZAxis)||Math.Abs(delta.Z)>1e-9)throw new ArgumentException("XY polyline and XY displacement required");foreach(int i in indices){if(i<0||i>=p.NumberOfVertices)throw new ArgumentException("Invalid vertex index");var q=p.GetPoint2dAt(i);p.SetPointAt(i,new(q.X+delta.X,q.Y+delta.Y));}}
   output.Add(new {handle=e.Handle.ToString(),indices});
  }return new {ok=true,modified=output};
 }
 static object Select(JsonElement a,Database db,Transaction tr,Editor ed){
  var pts=new Point3dCollection();foreach(var p in a.GetProperty("points").EnumerateArray())pts.Add(P(p).TransformBy(ed.CurrentUserCoordinateSystem.Inverse()));
  if(pts.Count<3||pts.Count>50)throw new ArgumentException("3..50 vertices required");
  var sel=B(a,"crossing",true)?ed.SelectCrossingPolygon(pts):ed.SelectWindowPolygon(pts);
  var ids=sel.Status==PromptStatus.OK?sel.Value.GetObjectIds():Array.Empty<ObjectId>();var wanted=ids.Where(id=>((Entity)tr.GetObject(id,OpenMode.ForRead)).OwnerId==Space(db)).ToArray();
  return new {ok=true,handles=wanted.Take(100).Select(id=>id.Handle.ToString()).ToArray(),count=wanted.Length,truncated=wanted.Length>100,scope="active_space_current_view",status=sel.Status.ToString()};
 }
 static LayerTableRecord Layer(Database db,Transaction tr,string n,bool write=false){var lt=(LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead);if(!lt.Has(n))throw new ArgumentException("Missing layer: "+n);var l=(LayerTableRecord)tr.GetObject(lt[n],write?OpenMode.ForWrite:OpenMode.ForRead);if(l.IsDependent)throw new ArgumentException("Xref-dependent layer unsupported");return l;}
 static object Rename(JsonElement a,Database db,Transaction tr){var old=S(a,"old");var n=S(a,"new");if(old.Equals("0",StringComparison.OrdinalIgnoreCase)||old.Equals("Defpoints",StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Protected layer");var l=Layer(db,tr,old,true);l.Name=n;return new {ok=true,old,@new=l.Name};}
 static object Merge(JsonElement a,Database db,Transaction tr){
  var sources=a.GetProperty("sources").EnumerateArray().Select(x=>x.GetString()!).ToArray();if(sources.Length==0)throw new ArgumentException("Sources required");var target=Layer(db,tr,S(a,"target"));if(target.IsLocked)throw new ArgumentException("Target layer locked");var ids=new HashSet<ObjectId>();
  foreach(var s in sources){if(s.Equals("0",StringComparison.OrdinalIgnoreCase)||s.Equals("Defpoints",StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Protected source layer");var l=Layer(db,tr,s);if(l.IsLocked||l.ObjectId==target.ObjectId)throw new ArgumentException("Locked source or source=target");ids.Add(l.ObjectId);}
  int count=0;var touched=new List<string>();var bt=(BlockTable)tr.GetObject(db.BlockTableId,OpenMode.ForRead);
  foreach(ObjectId bid in bt){var block=(BlockTableRecord)tr.GetObject(bid,OpenMode.ForRead);if(block.IsFromExternalReference)continue;bool hit=false;foreach(ObjectId eid in block){var e=tr.GetObject(eid,OpenMode.ForRead) as Entity;if(e==null)continue;
    var entities=new List<Entity>{e};if(e is BlockReference br)foreach(ObjectId aid in br.AttributeCollection)entities.Add((Entity)tr.GetObject(aid,OpenMode.ForRead));
    foreach(var ent in entities)if(ids.Contains(ent.LayerId)){if(!block.IsLayout&&!B(a,"include_blocks"))throw new ArgumentException("Source used in block definition; include_blocks=true required");ent.UpgradeOpen();ent.LayerId=target.ObjectId;count++;hit=true;}
   }if(hit&&!block.IsLayout)touched.Add(block.Name);}
  if(ids.Contains(db.Clayer))db.Clayer=target.ObjectId;
  var deletable=new ObjectIdCollection(ids.ToArray());db.Purge(deletable);if(B(a,"delete_sources",true)){if(deletable.Count!=ids.Count)throw new ArgumentException("Source layer still referenced; nothing committed");foreach(ObjectId id in deletable)tr.GetObject(id,OpenMode.ForWrite).Erase();}
  return new {ok=true,changed=count,target=target.Name,blocks_touched=touched,deleted=B(a,"delete_sources",true)?sources:Array.Empty<string>()};
 }
 static object Modify(JsonElement a,Database db,Transaction tr){
  var where=a.GetProperty("where");var set=a.GetProperty("changes");if(where.EnumerateObject().Any(x=>x.Name!="layer"&&x.Name!="type"&&x.Name!="color"))throw new ArgumentException("where supports exact layer/type/color only");if(!where.EnumerateObject().Any())throw new ArgumentException("Explicit where predicate required");if(set.EnumerateObject().Any(x=>x.Name!="layer"&&x.Name!="color"&&x.Name!="linetype"&&x.Name!="lineweight"))throw new ArgumentException("Unsupported property");if(!set.EnumerateObject().Any())throw new ArgumentException("changes required");
  ObjectId target=Has(set,"layer")?Layer(db,tr,S(set,"layer")).ObjectId:ObjectId.Null;if(!target.IsNull&&((LayerTableRecord)tr.GetObject(target,OpenMode.ForRead)).IsLocked)throw new ArgumentException("Target layer locked");
  var space=(BlockTableRecord)tr.GetObject(Space(db),OpenMode.ForRead);var found=new List<Entity>();int locked=0;
  foreach(ObjectId id in space){var e=(Entity)tr.GetObject(id,OpenMode.ForRead);if(Has(where,"layer")&&!e.Layer.Equals(S(where,"layer"),StringComparison.OrdinalIgnoreCase))continue;if(Has(where,"type")&&!e.GetRXClass().DxfName.Equals(S(where,"type"),StringComparison.OrdinalIgnoreCase))continue;if(Has(where,"color")&&e.ColorIndex!=(int)N(where,"color"))continue;if(((LayerTableRecord)tr.GetObject(e.LayerId,OpenMode.ForRead)).IsLocked){locked++;continue;}found.Add(e);}
  if(Has(a,"expect_count")&&found.Count!=(int)N(a,"expect_count"))throw new ArgumentException("Matched count changed; nothing committed");bool dry=B(a,"dry_run",true);int changed=0;
  foreach(var e in found){bool differs=(!target.IsNull&&e.LayerId!=target)||(Has(set,"color")&&e.ColorIndex!=(int)N(set,"color"))||(Has(set,"lineweight")&&(int)e.LineWeight!=(int)N(set,"lineweight"))||(Has(set,"linetype")&&!e.Linetype.Equals(S(set,"linetype"),StringComparison.OrdinalIgnoreCase));if(!differs)continue;changed++;if(dry)continue;e.UpgradeOpen();if(!target.IsNull)e.LayerId=target;if(Has(set,"color"))e.ColorIndex=checked((short)N(set,"color"));if(Has(set,"lineweight"))e.LineWeight=(LineWeight)(int)N(set,"lineweight");if(Has(set,"linetype"))e.Linetype=S(set,"linetype");}
  return new {ok=true,dry_run=dry,matched=found.Count,changed=dry?0:changed,would_change=changed,skipped_locked=locked,handles=found.Take(50).Select(e=>e.Handle.ToString()).ToArray(),truncated=found.Count>50};
 }
 static Dimension Dim(Database db,Transaction tr,string h)=>E(db,tr,h) as Dimension??throw new ArgumentException("DIMENSION required");
 static object DimEdit(JsonElement a,Database db,Transaction tr){
  var d=Dim(db,tr,S(a,"handle"));if(Has(a,"style")){var t=(DimStyleTable)tr.GetObject(db.DimStyleTableId,OpenMode.ForRead);if(!t.Has(S(a,"style")))throw new ArgumentException("Missing dimension style");d.DimensionStyle=t[S(a,"style")];}
  if(Has(a,"plot_scale")){double n=N(a,"plot_scale");if(n<=0)throw new ArgumentException("Positive plot_scale required");if(d.Annotative==AnnotativeStates.True)throw new ArgumentException("Annotative dimensions require context handling, not DIMSCALE override");d.Dimscale=n;}
  if(Has(a,"text_position"))d.TextPosition=P(a.GetProperty("text_position"));
  if(Has(a,"line_point")){var p=P(a.GetProperty("line_point"));if(d is RotatedDimension r)r.DimLinePoint=p;else if(d is AlignedDimension al)al.DimLinePoint=p;else throw new ArgumentException("line_point supports rotated/aligned dimensions only");}
  d.RecomputeDimensionBlock(true);return new {ok=true,handle=d.Handle.ToString(),measurement=d.Measurement,plot_scale=d.Dimscale,text_position=XYZ(d.TextPosition),text_override=d.DimensionText};
 }
 static object DimArrange(JsonElement a,Database db,Transaction tr){
  var hs=Handles(a);var origin=P(a.GetProperty("origin"));double gap=N(a,"spacing");if(gap<=0)throw new ArgumentException("Positive spacing required");double angle=N(a,"angle_deg")*Math.PI/180;var normal=new Vector3d(-Math.Sin(angle),Math.Cos(angle),0);var output=new List<object>();
  for(int i=0;i<hs.Count;i++){var d=Dim(db,tr,hs[i]);double direction=d is RotatedDimension r?r.Rotation:d is AlignedDimension al?Math.Atan2(al.XLine2Point.Y-al.XLine1Point.Y,al.XLine2Point.X-al.XLine1Point.X):throw new ArgumentException("Rotated/aligned only");if(Math.Abs(Math.Sin(direction-angle))>1e-8)throw new ArgumentException("All dimensions must parallel angle_deg");if(!d.Normal.IsEqualTo(Vector3d.ZAxis))throw new ArgumentException("XY dimensions required");var p=origin+normal*(gap*i);if(d is RotatedDimension rr)rr.DimLinePoint=p;else ((AlignedDimension)d).DimLinePoint=p;d.UsingDefaultTextPosition=true;d.RecomputeDimensionBlock(true);output.Add(new {handle=hs[i],line_point=XYZ(p),measurement=d.Measurement});}
  return new {ok=true,dimensions=output,text_position_reset=true};
 }
 static object Order(JsonElement a,Database db,Transaction tr){
  var hs=Handles(a);var es=hs.Select(h=>E(db,tr,h)).ToArray();var owner=(BlockTableRecord)tr.GetObject(es[0].OwnerId,OpenMode.ForRead);var table=(DrawOrderTable)tr.GetObject(owner.DrawOrderTableId,OpenMode.ForWrite);var ids=new ObjectIdCollection(es.Select(e=>e.ObjectId).ToArray());var mode=S(a,"position");
  if(mode=="top")table.MoveToTop(ids);else if(mode=="bottom")table.MoveToBottom(ids);else {var anchor=E(db,tr,S(a,"relative_to"),false);if(ids.Contains(anchor.ObjectId))throw new ArgumentException("Anchor must not be selected");if(mode=="above")table.MoveAbove(ids,anchor.ObjectId);else if(mode=="below")table.MoveBelow(ids,anchor.ObjectId);else throw new ArgumentException("position: top/bottom/above/below");}
  var all=table.GetFullDrawOrder(0).Cast<ObjectId>().ToArray();return new {ok=true,position=mode,order=es.Select(e=>new {handle=e.Handle.ToString(),index=Array.IndexOf(all,e.ObjectId)}).ToArray(),total=all.Length};
 }
 static object Profile(JsonElement a,Database db,Transaction tr){
  var config=a.GetProperty("settings");var allowed=new[]{"current_layer","textstyle","dimstyle","plot_scale"};
  if(config.EnumerateObject().Any(p=>!allowed.Contains(p.Name)))throw new ArgumentException("settings: current_layer/textstyle/dimstyle/plot_scale only; existing named styles required");
  if(Has(config,"current_layer")){var layer=Layer(db,tr,S(config,"current_layer"));if(layer.IsLocked||layer.IsFrozen||layer.IsOff)throw new ArgumentException("Current layer must be on, thawed and unlocked");db.Clayer=layer.ObjectId;}
  if(Has(config,"textstyle")){var t=(TextStyleTable)tr.GetObject(db.TextStyleTableId,OpenMode.ForRead);if(!t.Has(S(config,"textstyle")))throw new ArgumentException("Missing textstyle");db.Textstyle=t[S(config,"textstyle")];}
  if(Has(config,"dimstyle")){var t=(DimStyleTable)tr.GetObject(db.DimStyleTableId,OpenMode.ForRead);if(!t.Has(S(config,"dimstyle")))throw new ArgumentException("Missing dimstyle");var id=t[S(config,"dimstyle")];db.Dimstyle=id;db.SetDimstyleData((DimStyleTableRecord)tr.GetObject(id,OpenMode.ForRead));}
  if(Has(config,"plot_scale")){double scale=N(config,"plot_scale");if(scale<=0)throw new ArgumentException("Positive scale required");db.Dimscale=scale;}
  return new {ok=true,current_layer=((LayerTableRecord)tr.GetObject(db.Clayer,OpenMode.ForRead)).Name,textstyle=((TextStyleTableRecord)tr.GetObject(db.Textstyle,OpenMode.ForRead)).Name,dimstyle=((DimStyleTableRecord)tr.GetObject(db.Dimstyle,OpenMode.ForRead)).Name,plot_scale=db.Dimscale,note="Existing company styles selected; existing entities and arch role-layer mapping are unchanged"};
 }
}
