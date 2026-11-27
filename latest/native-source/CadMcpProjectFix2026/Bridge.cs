using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using AcApp=Autodesk.AutoCAD.ApplicationServices.Core.Application;
using System.Text.Json;
namespace CadMcpProjectFix;
public class Bridge {
 static string cached="", token="", document="";
 static DateTime expires;
 static string S(JsonElement a,string k,string d="")=>a.TryGetProperty(k,out var v)&&v.ValueKind!=JsonValueKind.Null?v.GetString()??d:d;
 static double N(JsonElement a,string k,double d=0)=>a.TryGetProperty(k,out var v)?v.GetDouble():d;
 static double[] XY(Point3d p)=>new[]{p.X,p.Y};
 static double[] XY2(Point2d p)=>new[]{p.X,p.Y};
 static double Deg(double x)=>x*180/Math.PI;
 static object Chunk(int offset)=>new {ok=true,token,offset,data=cached.Substring(offset,Math.Min(2200,cached.Length-offset)),length=cached.Length};
 [LispFunction("MCPPROJECTFIX2026")]
 public static ResultBuffer Run(ResultBuffer args){
  object result;
  try{
   var a=JsonDocument.Parse((string)args.AsArray()[0].Value).RootElement;
   var doc=AcApp.DocumentManager.MdiActiveDocument??throw new InvalidOperationException("No document");
   if(!string.Equals(doc.Name,S(a,"document"),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Active document changed");
   var op=S(a,"op");
   if(op=="chunk"){
    if(S(a,"token")!=token||document!=doc.Name||DateTime.UtcNow>expires)throw new InvalidOperationException("Snapshot expired or wrong document");
    result=Chunk((int)N(a,"offset"));
   }else{
    using var l=doc.LockDocument();using var tr=doc.Database.TransactionManager.StartTransaction();var db=doc.Database;
    result=op switch {
     "ping"=>new {ok=true,version="1.0.0"},
     "entities"=>Entities(a,db,tr),
     "viewports"=>Viewports(a,db,tr),
     "viewport_delete"=>DeleteViewport(a,db,tr),
     "dimension_chain"=>Dimensions(a,db,tr),
     _=>throw new ArgumentException("Unknown operation")};
    tr.Commit();
    var json=JsonSerializer.Serialize(result);
    if(json.Length>6000){cached=json;token=Guid.NewGuid().ToString("N");document=doc.Name;expires=DateTime.UtcNow.AddMinutes(2);result=Chunk(0);}
   }
  }catch(System.Exception e){result=new {ok=false,error=e.Message};}
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(result)));
 }
 static string Type(Entity e)=>e.GetRXClass().Name.Replace("AcDb","").ToUpperInvariant();
 static bool Matches(Entity e,string filter){string t=Type(e);return filter==""||t==filter||e.GetRXClass().DxfName==filter||(filter=="DIMENSION"&&e is Dimension);}
 static object Entities(JsonElement a,Database db,Transaction tr){
  var b=(BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForRead);
  string type=S(a,"type_filter").ToUpperInvariant(),layer=S(a,"layer_filter");int offset=(int)N(a,"offset"),limit=(int)N(a,"limit",100),total=0;
  HashSet<string>? fields=null;if(a.TryGetProperty("fields",out var f)&&f.ValueKind==JsonValueKind.Array)fields=f.EnumerateArray().Select(x=>x.GetString()!).ToHashSet();
  var rows=new List<object>();var errors=new List<object>();
  foreach(ObjectId id in b){
   if(tr.GetObject(id,OpenMode.ForRead) is not Entity e)continue;
   if(!Matches(e,type)||(layer!=""&&!string.Equals(e.Layer,layer,StringComparison.OrdinalIgnoreCase)))continue;
   int index=total++;if(index<offset||rows.Count>=limit)continue;
   var props=new Dictionary<string,object>();bool all=fields==null;
   bool Want(string k)=>all||fields!.Contains("properties")||fields.Contains("properties."+k);
   try{
    if(Want("bounding_box")){try{var ext=e.GeometricExtents;props["bounding_box"]=new{min=XY(ext.MinPoint),max=XY(ext.MaxPoint)};}catch{}}
    if(all||fields!.Any(x=>x.StartsWith("properties"))){
     void Put(string k,object v){if(Want(k))props[k]=v;}
     switch(e){
      case Line x:Put("start",XY(x.StartPoint));Put("end",XY(x.EndPoint));Put("length",x.Length);break;
      case Circle x:Put("center",XY(x.Center));Put("radius",x.Radius);break;
      case Arc x:Put("center",XY(x.Center));Put("radius",x.Radius);Put("start_angle",Deg(x.StartAngle));Put("end_angle",Deg(x.EndAngle));Put("length",x.Length);break;
      case Polyline x:Put("points",Enumerable.Range(0,x.NumberOfVertices).Select(i=>XY(x.GetPoint3dAt(i))).ToArray());Put("bulges",Enumerable.Range(0,x.NumberOfVertices).Select(i=>x.GetBulgeAt(i)*(x.Normal.Z<0?-1:1)).ToArray());Put("closed",x.Closed);Put("length",x.Length);break;
      case DBText x:Put("text",x.TextString);Put("insertion",XY(x.Position));Put("height",x.Height);Put("rotation",Deg(x.Rotation));break;
      case MText x:Put("text",x.Contents);Put("insertion",XY(x.Location));Put("char_height",x.TextHeight);Put("rotation",Deg(x.Rotation));break;
      case BlockReference x:Put("insertion",XY(x.Position));Put("block_name",((BlockTableRecord)tr.GetObject(x.BlockTableRecord,OpenMode.ForRead)).Name);Put("x_scale",x.ScaleFactors.X);Put("y_scale",x.ScaleFactors.Y);Put("rotation_deg",Deg(x.Rotation));Put("mirrored",x.Normal.Z<0);if(Want("geometry_bbox")){try{var ext=x.GeometryExtentsBestFit();props["geometry_bbox"]=new{min=XY(ext.MinPoint),max=XY(ext.MaxPoint)};}catch{}}break;
      case Dimension x:Put("text_position",XY(x.TextPosition));break;
     }
    }
   }catch(System.Exception ex){errors.Add(new{handle=e.Handle.ToString(),error=ex.Message});}
   rows.Add(new {handle=e.Handle.ToString(),type=Type(e),layer=e.Layer,color=(int)e.ColorIndex,linetype=e.Linetype,visible=e.Visible,properties=props});
  }
  return new{ok=true,rows,total,errors,snapshot=true};
 }
 static (Viewport vp,Layout layout,bool main) Resolve(Database db,Transaction tr,string handle){
  var id=db.GetObjectId(false,new Handle(Convert.ToInt64(handle,16)),0);
  var vp=tr.GetObject(id,OpenMode.ForRead) as Viewport??throw new ArgumentException("Not a paper viewport");
  var owner=(BlockTableRecord)tr.GetObject(vp.OwnerId,OpenMode.ForRead);
  if(!owner.IsLayout||owner.ObjectId==SymbolUtilityServices.GetBlockModelSpaceId(db))throw new ArgumentException("Not a paper layout");
  var layout=(Layout)tr.GetObject(owner.LayoutId,OpenMode.ForRead);var ids=layout.GetViewports();
  if(ids.Count==0||!ids.Contains(id))throw new InvalidOperationException("Unknown viewport identity; operation refused");
  return(vp,layout,ids[0]==id);
 }
 static object Viewports(JsonElement a,Database db,Transaction tr){
  var dict=(DBDictionary)tr.GetObject(db.LayoutDictionaryId,OpenMode.ForRead);string wanted=S(a,"layout");var rows=new List<object>();bool found=wanted=="";
  foreach(DBDictionaryEntry entry in dict){var layout=(Layout)tr.GetObject(entry.Value,OpenMode.ForRead);if(layout.ModelType||wanted!=""&&!string.Equals(layout.LayoutName,wanted,StringComparison.OrdinalIgnoreCase))continue;found=true;var ids=layout.GetViewports();
   foreach(ObjectId id in ids){var v=(Viewport)tr.GetObject(id,OpenMode.ForRead);rows.Add(new{handle=v.Handle.ToString(),layout=layout.LayoutName,center=XY(v.CenterPoint),width=v.Width,height=v.Height,view_center=XY2(v.ViewCenter),view_height=v.ViewHeight,scale=v.CustomScale,locked=v.Locked,status=v.On?1:0,id=v.Number,is_main=id==ids[0],identity_source="Layout.GetViewports"});}
  }
  if(!found)throw new ArgumentException("Layout not found");return new{ok=true,viewports=rows,count=rows.Count,note="id may change after reopen; handle identifies entity; is_main uses layout ownership order"};
 }
 static object DeleteViewport(JsonElement a,Database db,Transaction tr){
  var(v,l,main)=Resolve(db,tr,S(a,"handle"));if(main)throw new ArgumentException("Paper-space main viewport is protected; force cannot override");
  if(((LayerTableRecord)tr.GetObject(v.LayerId,OpenMode.ForRead)).IsLocked)throw new ArgumentException("Locked layer");
  string h=v.Handle.ToString();v.UpgradeOpen();v.Erase();return new{ok=true,handle=h,layout=l.LayoutName,was_main=false};
 }
 static Point3d P(JsonElement a){var x=a.EnumerateArray().Select(z=>z.GetDouble()).ToArray();if(x.Length<2||x.Length>3||x.Any(z=>!double.IsFinite(z)))throw new ArgumentException("Finite XY/XYZ required");return new(x[0],x[1],x.Length==3?x[2]:0);}
 static object Dimensions(JsonElement a,Database db,Transaction tr){
  if(!db.TileMode&&Convert.ToInt32(AcApp.GetSystemVariable("CVPORT"))==1)throw new ArgumentException("Unit-aware dimensions require model space");
  var pts=a.GetProperty("points").EnumerateArray().Select(P).ToArray();double angle=N(a,"angle_deg")*Math.PI/180,scale=N(a,"plot_scale"),mm=N(a,"mm_per_unit"),text=N(a,"paper_text_height",2.5);if(pts.Length<2||pts.Length>50||scale<=0||mm<=0||text<=0)throw new ArgumentException("Invalid dimensional parameters");
  var axis=new Vector3d(Math.Cos(angle),Math.Sin(angle),0);var normal=new Vector3d(-axis.Y,axis.X,0);var origin=P(a.GetProperty("line_point"));double Proj(Point3d p)=>(p-Point3d.Origin).DotProduct(axis);pts=pts.OrderBy(Proj).ToArray();if(pts.Any(p=>Math.Abs(p.Z-origin.Z)>1e-7))throw new ArgumentException("Different elevations");for(int i=1;i<pts.Length;i++)if(Proj(pts[i])-Proj(pts[i-1])<1e-8)throw new ArgumentException("Duplicate projected points");
  var styles=(DimStyleTable)tr.GetObject(db.DimStyleTableId,OpenMode.ForRead);var style=S(a,"style")==""?db.Dimstyle:styles[S(a,"style")];var layers=(LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead);var layer=S(a,"layer")==""?db.Clayer:layers[S(a,"layer")];if(((LayerTableRecord)tr.GetObject(layer,OpenMode.ForRead)).IsLocked)throw new ArgumentException("Locked layer");
  var owner=(BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForWrite);var rows=new List<object>();
  void Add(Point3d p,Point3d q,Point3d line,bool overall){var d=new RotatedDimension(angle,p,q,line,"",style);d.SetDatabaseDefaults(db);d.DimensionStyle=style;d.LayerId=layer;d.Dimscale=scale;d.Dimlfac=mm;d.Dimtxt=text/mm;d.Dimasz=text/mm;d.Dimgap=.625/mm;d.Dimexo=.625/mm;d.Dimexe=1.25/mm;d.Dimdec=0;var id=owner.AppendEntity(d);tr.AddNewlyCreatedDBObject(d,true);d.RecomputeDimensionBlock(true);rows.Add(new{handle=id.Handle.ToString(),measurement=d.Measurement,geometric_length=Math.Abs(Proj(q)-Proj(p)),overall,text_height_model=d.Dimtxt*d.Dimscale,dimlfac=d.Dimlfac});}
  for(int i=1;i<pts.Length;i++)Add(pts[i-1],pts[i],origin,false);
  if(a.GetProperty("overall").GetBoolean()){double spacing=N(a,"overall_spacing");if(spacing<=0)throw new ArgumentException("Positive spacing required");Add(pts[0],pts[^1],origin+normal*spacing,true);}
  return new{ok=true,dimensions=rows,associative=false,points_sorted=true,plot_scale=scale,mm_per_unit=mm,display_units="mm",paper_text_height=text};
 }
}
