using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.PlottingServices;
using AcApp=Autodesk.AutoCAD.ApplicationServices.Core.Application;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text;
using System.Security.Cryptography;
using System.IO.Compression;
using System.IO;
namespace CadMcpBuilding;
public class Bridge {
 const string RecordKey="CADMCP_BUILDING";
 static string output="", outputToken="", outputDocument="";
 static string upload="", uploadToken="", uploadDocument="";
 static DateTime outputExpires,uploadExpires;
 static string S(JsonElement e,string k,string fallback="")=>e.TryGetProperty(k,out var v)&&v.ValueKind==JsonValueKind.String?v.GetString()??fallback:fallback;
 static double N(JsonElement e,string k,double fallback=0)=>e.TryGetProperty(k,out var v)?v.GetDouble():fallback;
 static bool B(JsonElement e,string k,bool fallback=false)=>e.TryGetProperty(k,out var v)?v.GetBoolean():fallback;
 static JsonElement J(object value)=>JsonSerializer.SerializeToElement(value);
 static double[] P(Point3d p)=>new[]{p.X,p.Y,p.Z};
 static Point3d Pt(JsonElement e)=>new(e[0].GetDouble(),e[1].GetDouble(),e.GetArrayLength()>2?e[2].GetDouble():0);
 static ObjectId Id(Database db,string h)=>db.GetObjectId(false,new Handle(Convert.ToInt64(h,16)),0);
 static string Compress(string s){using var m=new MemoryStream();using(var g=new GZipStream(m,CompressionMode.Compress,true)){var bytes=Encoding.UTF8.GetBytes(s);g.Write(bytes);}return Convert.ToBase64String(m.ToArray());}
 static string Expand(string s){using var m=new MemoryStream(Convert.FromBase64String(s));using var g=new GZipStream(m,CompressionMode.Decompress);using var r=new StreamReader(g,Encoding.UTF8);var text=r.ReadToEnd();if(text.Length>8000000)throw new ArgumentException("Request too large");return text;}
 static object Part(int offset)=>new{ok=true,compressed=true,token=outputToken,offset,length=output.Length,data=output.Substring(offset,Math.Min(2200,output.Length-offset))};
 [LispFunction("MCPBUILDING2026")]
 public static ResultBuffer Run(ResultBuffer rb){
  object result;
  try {
   var a=JsonDocument.Parse((string)rb.AsArray()[0].Value).RootElement;
   var doc=AcApp.DocumentManager.MdiActiveDocument??throw new InvalidOperationException("No drawing");
   if(!string.Equals(doc.Name,S(a,"document"),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Active drawing changed");
   var op=S(a,"op");
   if(op=="chunk"){
    if(S(a,"token")!=outputToken||outputDocument!=doc.Name||DateTime.UtcNow>outputExpires)throw new InvalidOperationException("Expired response");
    result=Part((int)N(a,"offset"));
   }else if(op=="upload_start"){
    upload="";uploadToken=Guid.NewGuid().ToString("N");uploadDocument=doc.Name;uploadExpires=DateTime.UtcNow.AddMinutes(2);result=new{ok=true,upload_token=uploadToken};
   }else if(op=="upload_chunk"){
    if(S(a,"upload_token")!=uploadToken||uploadDocument!=doc.Name||DateTime.UtcNow>uploadExpires||(int)N(a,"offset")!=upload.Length)throw new InvalidOperationException("Invalid upload");
    upload+=S(a,"data");if(upload.Length>4000000)throw new InvalidOperationException("Upload too large");result=new{ok=true,length=upload.Length};
   }else {
    if(op=="uploaded"){
     if(S(a,"upload_token")!=uploadToken||uploadDocument!=doc.Name||DateTime.UtcNow>uploadExpires)throw new InvalidOperationException("Invalid upload");
     a=JsonDocument.Parse(Expand(upload)).RootElement;upload="";uploadToken="";op=S(a,"op");
     if(!string.Equals(doc.Name,S(a,"document"),StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException("Uploaded drawing changed");
    }
    using var l=doc.LockDocument();
    result=op switch {
     "snapshot"=>Snapshot(doc.Database,S(a,"scope","model")),
     "apply"=>Apply(doc.Database,a),
     "save_copy"=>SaveCopy(doc.Database,a),
     "verify_output"=>VerifyOutput(a),
     "pdf"=>Pdf(doc.Database,a),
     "ping"=>new{ok=true,version="1.0.0"},
     _=>throw new ArgumentException("Unknown building operation")};
    var json=JsonSerializer.Serialize(result);output=Compress(json);
    outputToken=Guid.NewGuid().ToString("N");outputDocument=doc.Name;outputExpires=DateTime.UtcNow.AddMinutes(2);result=Part(0);
   }
  }catch(System.Exception ex){result=new{ok=false,error=ex.Message};}
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(result)));
 }
 static object? Record(Entity e,Transaction tr){
  if(e.ExtensionDictionary.IsNull)return null;var dict=(DBDictionary)tr.GetObject(e.ExtensionDictionary,OpenMode.ForRead);
  if(!dict.Contains(RecordKey))return null;var x=(Xrecord)tr.GetObject(dict.GetAt(RecordKey),OpenMode.ForRead);
  return JsonDocument.Parse(string.Concat(x.Data.AsArray().Select(v=>v.Value as string??""))).RootElement.Clone();
 }
 static List<string> Xdata(Entity e,string app){using var x=e.GetXDataForApplication(app);return x==null?new():x.AsArray().Where(v=>v.TypeCode==1000).Select(v=>(string)v.Value).ToList();}
 static void SetRecord(Entity e,Transaction tr,JsonElement record){
  if(e.ExtensionDictionary.IsNull)e.CreateExtensionDictionary();var d=(DBDictionary)tr.GetObject(e.ExtensionDictionary,OpenMode.ForWrite);
  Xrecord x;if(d.Contains(RecordKey))x=(Xrecord)tr.GetObject(d.GetAt(RecordKey),OpenMode.ForWrite);else{x=new Xrecord();d.SetAt(RecordKey,x);tr.AddNewlyCreatedDBObject(x,true);}
  string s=record.GetRawText();var data=new List<TypedValue>();for(int i=0;i<s.Length;i+=200)data.Add(new TypedValue(1000,s.Substring(i,Math.Min(200,s.Length-i))));x.Data=new ResultBuffer(data.ToArray());
 }
 static Dictionary<string,object?> Row(Entity e,Transaction tr,string space){
  var layer=(LayerTableRecord)tr.GetObject(e.LayerId,OpenMode.ForRead);
  var r=new Dictionary<string,object?>{{"handle",e.Handle.ToString()},{"type",e.GetRXClass().DxfName},{"space",space},{"layer",e.Layer},{"locked",layer.IsLocked},{"color",(int)e.ColorIndex},{"linetype",e.Linetype},{"lineweight",(int)e.LineWeight},{"record",Record(e,tr)}};
  try{var ex=e.GeometricExtents;r["bbox"]=new{min=P(ex.MinPoint),max=P(ex.MaxPoint)};}catch{}
  r["arch_values"]=Xdata(e,"ACADMCP_ARCH");r["arch_handles"]=Xdata(e,"ACADMCP_ARCH_H");
  switch(e){
   case Line x:r["points"]=new[]{P(x.StartPoint),P(x.EndPoint)};r["length"]=x.Length;break;
   case Polyline x:r["points"]=Enumerable.Range(0,x.NumberOfVertices).Select(i=>P(x.GetPoint3dAt(i))).ToArray();r["bulges"]=Enumerable.Range(0,x.NumberOfVertices).Select(i=>x.GetBulgeAt(i)).ToArray();r["closed"]=x.Closed;r["normal"]=new[]{x.Normal.X,x.Normal.Y,x.Normal.Z};r["length"]=x.Length;break;
   case Arc x:r["center"]=P(x.Center);r["radius"]=x.Radius;r["start_angle"]=x.StartAngle;r["end_angle"]=x.EndAngle;r["length"]=x.Length;r["points"]=new[]{P(x.StartPoint),P(x.EndPoint)};r["normal"]=new[]{x.Normal.X,x.Normal.Y,x.Normal.Z};break;
   case Circle x:r["center"]=P(x.Center);r["radius"]=x.Radius;r["length"]=x.Circumference;r["normal"]=new[]{x.Normal.X,x.Normal.Y,x.Normal.Z};break;
   case Curve x:r["length"]=x.GetDistanceAtParameter(x.EndParam)-x.GetDistanceAtParameter(x.StartParam);break;
   case DBText x:r["text"]=x.TextString;r["position"]=P(x.Position);r["height"]=x.Height;r["rotation"]=x.Rotation;r["alignment_point"]=P(x.AlignmentPoint);r["text_style"]=x.TextStyleName;break;
   case MText x:r["text"]=x.Contents;r["position"]=P(x.Location);r["height"]=x.TextHeight;r["rotation"]=x.Rotation;break;
   case Table x:r["position"]=P(x.Position);r["cells"]=Enumerable.Range(0,x.Rows.Count).Select(i=>Enumerable.Range(0,x.Columns.Count).Select(j=>x.Cells[i,j].TextString).ToArray()).ToArray();break;
   case BlockReference x:
    var b=(BlockTableRecord)tr.GetObject(x.DynamicBlockTableRecord.IsNull?x.BlockTableRecord:x.DynamicBlockTableRecord,OpenMode.ForRead);
    r["block_name"]=b.Name;r["position"]=P(x.Position);r["rotation"]=x.Rotation;r["scale"]=new[]{x.ScaleFactors.X,x.ScaleFactors.Y,x.ScaleFactors.Z};
    var attrs=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);foreach(ObjectId id in x.AttributeCollection){if(tr.GetObject(id,OpenMode.ForRead) is AttributeReference v)attrs[v.Tag]=v.TextString;}r["attributes"]=attrs;r["xref"]=b.IsFromExternalReference;break;
  }
  return r;
 }
 static Dictionary<string,object?> Snapshot(Database db,string scope){
  if(scope!="model"&&scope!="all")throw new ArgumentException("scope=model/all");
  using var tr=db.TransactionManager.StartTransaction();var bt=(BlockTable)tr.GetObject(db.BlockTableId,OpenMode.ForRead);
  var rows=new List<object>();var errors=new List<object>();var used=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
  foreach(ObjectId bid in bt){var block=(BlockTableRecord)tr.GetObject(bid,OpenMode.ForRead);if(scope=="model"&&bid!=SymbolUtilityServices.GetBlockModelSpaceId(db))continue;
   if(block.IsFromExternalReference)continue;
   string space=bid==SymbolUtilityServices.GetBlockModelSpaceId(db)?"model":block.IsLayout?"layout:"+((Layout)tr.GetObject(block.LayoutId,OpenMode.ForRead)).LayoutName:"block:"+block.Name;
   foreach(ObjectId id in block){if(tr.GetObject(id,OpenMode.ForRead) is not Entity e)continue;used.Add(e.Layer);try{var row=Row(e,tr,space);row["space_units"]=space=="model"?(int)db.Insunits:block.IsLayout?(((Layout)tr.GetObject(block.LayoutId,OpenMode.ForRead)).PlotPaperUnits==PlotPaperUnit.Inches?1:4):(int)block.Units;rows.Add(row);}catch(System.Exception ex){errors.Add(new{handle=e.Handle.ToString(),error=ex.Message});}if(rows.Count>200000)throw new ArgumentException("Snapshot exceeds200000 entities");}
  }
  var layers=new List<object>();foreach(ObjectId id in (LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead)){var x=(LayerTableRecord)tr.GetObject(id,OpenMode.ForRead);layers.Add(new{name=x.Name,locked=x.IsLocked,used=used.Contains(x.Name)});}
  var fonts=new List<object>();foreach(ObjectId id in (TextStyleTable)tr.GetObject(db.TextStyleTableId,OpenMode.ForRead)){var x=(TextStyleTableRecord)tr.GetObject(id,OpenMode.ForRead);foreach(var file in new[]{x.FileName,x.BigFontFileName}.Where(v=>!string.IsNullOrWhiteSpace(v))){bool found;try{found=File.Exists(HostApplicationServices.Current.FindFile(file,db,FindFileHint.FontFile));}catch{found=false;}fonts.Add(new{style=x.Name,file,found});}}
  var xrefs=new List<object>();foreach(ObjectId id in bt){var x=(BlockTableRecord)tr.GetObject(id,OpenMode.ForRead);if(x.IsFromExternalReference)xrefs.Add(new{name=x.Name,path=x.PathName,status=x.XrefStatus.ToString()});}
  var layouts=new List<object>();var ld=(DBDictionary)tr.GetObject(db.LayoutDictionaryId,OpenMode.ForRead);var plotStyles=PlotSettingsValidator.Current.GetPlotStyleSheetList().Cast<string>().ToHashSet(StringComparer.OrdinalIgnoreCase);
  foreach(DBDictionaryEntry de in ld){var x=(Layout)tr.GetObject(de.Value,OpenMode.ForRead);layouts.Add(new{name=x.LayoutName,style=x.CurrentStyleSheet,style_found=string.IsNullOrEmpty(x.CurrentStyleSheet)||plotStyles.Contains(x.CurrentStyleSheet),device=x.PlotConfigurationName});}
  var state=new Dictionary<string,object?>{{"ok",true},{"document",AcApp.DocumentManager.GetDocument(db)?.Name??db.Filename},{"database_session",db.UnmanagedObject.ToInt64()},{"fingerprint",db.FingerprintGuid.ToString()},{"units",(int)db.Insunits},{"scope",scope},{"rows",rows},{"layers",layers},{"fonts",fonts},{"xrefs",xrefs},{"layouts",layouts},{"errors",errors},{"complete",errors.Count==0}};
  state["token"]=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(state))));return state;
 }
 static void Check(Database db,JsonElement a){var scope=S(a,"scope","model");var now=Snapshot(db,scope);if(S(a,"expected_token")!=(string)now["token"]!)throw new InvalidOperationException("Preview expired; read and preview again");if(!(bool)now["complete"]!)throw new InvalidOperationException("Incomplete drawing snapshot");}
 static void Layer(Database db,Transaction tr,string name){if(string.IsNullOrWhiteSpace(name))throw new ArgumentException("Layer required");var lt=(LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead);if(lt.Has(name)){var l=(LayerTableRecord)tr.GetObject(lt[name],OpenMode.ForRead);if(l.IsLocked)throw new ArgumentException("Locked layer: "+name);return;}lt.UpgradeOpen();var fresh=new LayerTableRecord{Name=name};lt.Add(fresh);tr.AddNewlyCreatedDBObject(fresh,true);}
 static Entity Create(Database db,Transaction tr,JsonElement x){
  Entity e;switch(S(x,"type")){
   case "LINE":e=new Line(Pt(x.GetProperty("start")),Pt(x.GetProperty("end")));break;
   case "POLYLINE":var p=new Polyline();var pts=x.GetProperty("points").EnumerateArray().ToArray();for(int i=0;i<pts.Length;i++){var q=Pt(pts[i]);p.AddVertexAt(i,new Point2d(q.X,q.Y),0,0,0);p.Elevation=q.Z;}p.Closed=B(x,"closed",true);e=p;break;
   case "CIRCLE":e=new Circle(Pt(x.GetProperty("center")),Vector3d.ZAxis,N(x,"radius"));break;
   case "ARC":e=new Arc(Pt(x.GetProperty("center")),N(x,"radius"),N(x,"start_angle"),N(x,"end_angle"));break;
   case "TEXT":var text=new DBText{TextString=S(x,"text"),Height=N(x,"height"),Rotation=N(x,"rotation"),TextStyleId=db.Textstyle};if(B(x,"centered",true)){text.HorizontalMode=TextHorizontalMode.TextCenter;text.VerticalMode=TextVerticalMode.TextVerticalMid;text.AlignmentPoint=Pt(x.GetProperty("position"));}else text.Position=Pt(x.GetProperty("position"));e=text;break;
   case "TABLE":var cells=x.GetProperty("cells").EnumerateArray().Select(r=>r.EnumerateArray().Select(v=>v.GetString()??"").ToArray()).ToArray();var table=new Table{TableStyle=db.Tablestyle,Position=Pt(x.GetProperty("position"))};table.SetSize(cells.Length,cells[0].Length);table.UnmergeCells(CellRange.Create(table,0,0,cells.Length-1,cells[0].Length-1));table.SetRowHeight(N(x,"row_height"));table.SetColumnWidth(N(x,"column_width"));for(int i=0;i<cells.Length;i++)for(int j=0;j<cells[i].Length;j++){table.Cells[i,j].TextString=cells[i][j];table.Cells[i,j].TextHeight=N(x,"text_height");}table.GenerateLayout();e=table;break;
   default:throw new ArgumentException("Unsupported primitive");
  }
  e.SetDatabaseDefaults(db);e.Layer=S(x,"layer");if(x.TryGetProperty("color",out var color))e.ColorIndex=color.GetInt16();if(x.TryGetProperty("linetype",out var linetype))e.Linetype=linetype.GetString();if(x.TryGetProperty("lineweight",out var weight))e.LineWeight=(LineWeight)weight.GetInt32();return e;
 }
 static object Apply(Database db,JsonElement a){
  if(!db.TileMode)throw new ArgumentException("Use model tab");Check(db,a);
  var plan=a.GetProperty("plan");using var tr=db.TransactionManager.StartTransaction();var model=(BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForWrite);var created=new List<string>();var changed=new List<string>();var refs=new Dictionary<string,string>();var records=new List<(Entity,JsonElement)>();
  if(plan.TryGetProperty("updates",out var updates))foreach(var u in updates.EnumerateArray()){
   var e=(Entity)tr.GetObject(Id(db,S(u,"handle")),OpenMode.ForWrite);if(e.OwnerId!=model.ObjectId)throw new ArgumentException("Update outside model");if(((LayerTableRecord)tr.GetObject(e.LayerId,OpenMode.ForRead)).IsLocked)throw new ArgumentException("Locked entity");
   if(B(u,"delete")){e.Erase();changed.Add(e.Handle.ToString());continue;}
   if(u.TryGetProperty("text",out var value)){if(e is DBText t)t.TextString=value.GetString();else if(e is MText mt)mt.Contents=value.GetString();else throw new ArgumentException("Text entity required");}
   if(u.TryGetProperty("position",out var position)){if(e is DBText dt){if(dt.HorizontalMode==TextHorizontalMode.TextLeft)dt.Position=Pt(position);else dt.AlignmentPoint=Pt(position);dt.AdjustAlignment(db);}else if(e is MText mt)mt.Location=Pt(position);else throw new ArgumentException("Text position target required");}
   if(u.TryGetProperty("cells",out var cellsValue)){if(e is not Table tab)throw new ArgumentException("Table target required");var cells=cellsValue.EnumerateArray().Select(r=>r.EnumerateArray().Select(v=>v.GetString()??"").ToArray()).ToArray();tab.SetSize(cells.Length,cells[0].Length);tab.UnmergeCells(CellRange.Create(tab,0,0,cells.Length-1,cells[0].Length-1));for(int i=0;i<cells.Length;i++)for(int j=0;j<cells[i].Length;j++)tab.Cells[i,j].TextString=cells[i][j];tab.GenerateLayout();}
   if(u.TryGetProperty("points",out var points)){if(e is not Line l)throw new ArgumentException("Line update required");l.StartPoint=Pt(points[0]);l.EndPoint=Pt(points[1]);}
   if(u.TryGetProperty("attributes",out var attrs)){if(e is not BlockReference br)throw new ArgumentException("Block required");var required=attrs.EnumerateObject().ToDictionary(p=>p.Name,p=>p.Value.GetString()??"",StringComparer.OrdinalIgnoreCase);foreach(ObjectId id in br.AttributeCollection){var ar=(AttributeReference)tr.GetObject(id,OpenMode.ForWrite);if(required.Remove(ar.Tag,out var val))ar.TextString=val;}if(required.Count>0)throw new ArgumentException("Attribute missing: "+string.Join(",",required.Keys));}
   if(u.TryGetProperty("record",out var record))SetRecord(e,tr,record);
   if(u.TryGetProperty("arch_values",out var values)){var rt=(RegAppTable)tr.GetObject(db.RegAppTableId,OpenMode.ForRead);if(!rt.Has("ACADMCP_ARCH")){rt.UpgradeOpen();var reg=new RegAppTableRecord{Name="ACADMCP_ARCH"};rt.Add(reg);tr.AddNewlyCreatedDBObject(reg,true);}e.XData=new ResultBuffer(new[]{new TypedValue(1001,"ACADMCP_ARCH")}.Concat(values.EnumerateArray().Select(v=>new TypedValue(1000,v.GetString()))).ToArray());}
   if(e is DBText aligned)aligned.AdjustAlignment(db);
   changed.Add(e.Handle.ToString());
  }
  if(plan.TryGetProperty("entities",out var entities))foreach(var x in entities.EnumerateArray()){
   Layer(db,tr,S(x,"layer"));var e=Create(db,tr,x);model.AppendEntity(e);tr.AddNewlyCreatedDBObject(e,true);if(e is DBText txt)txt.AdjustAlignment(db);if(x.TryGetProperty("record",out var record))records.Add((e,record));if(x.TryGetProperty("id",out var key))refs.Add(key.GetString()!,e.Handle.ToString());created.Add(e.Handle.ToString());if(created.Count>10000)throw new ArgumentException("Too many entities");
  }
  foreach(var (entity,value) in records){var json=value.GetRawText();foreach(var pair in refs)json=json.Replace(JsonSerializer.Serialize("@"+pair.Key),JsonSerializer.Serialize(pair.Value));SetRecord(entity,tr,JsonDocument.Parse(json).RootElement);}
  var readback=created.Select(h=>Row((Entity)tr.GetObject(Id(db,h),OpenMode.ForRead),tr,"model")).ToArray();
  if(readback.Length!=created.Count)throw new InvalidOperationException("Created object readback mismatch");
  tr.Commit();return new{ok=true,created,updated=changed,entity_count=created.Count,references=refs,atomic=true,readback_verified=true};
 }
 static object VerifyOutput(JsonElement a){var path=Path.GetFullPath(S(a,"path"));var bytes=File.ReadAllBytes(path);var sha=Convert.ToHexString(SHA256.HashData(bytes));if(sha!=S(a,"sha256"))throw new InvalidDataException("Export file changed");return new{ok=true,sha256=sha,bytes=bytes.Length};}
 static object SaveCopy(Database db,JsonElement a){
  Check(db,a);var path=Path.GetFullPath(S(a,"path"));if(File.Exists(path))throw new ArgumentException("Output exists");
  var mapping=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
  var watched=new List<Database>();
  IdMappingEventHandler capture=(_,evt)=>{
   foreach(IdPair pair in evt.IdMapping){
    if(pair.Key.IsNull||pair.Value.IsNull)continue;
    if(pair.Key.Database.UnmanagedObject==db.UnmanagedObject&&pair.Value.Database.UnmanagedObject!=db.UnmanagedObject&&pair.Value.Handle.Value!=0)mapping[pair.Key.Handle.ToString()]=pair.Value.Handle.ToString();
   }
  };
  EventHandler constructed=(sender,_)=>{if(sender is Database fresh){watched.Add(fresh);fresh.WblockMappingAvailable+=capture;fresh.BeginDeepCloneTranslation+=capture;}};
  Database copy;db.WblockMappingAvailable+=capture;db.BeginDeepCloneTranslation+=capture;Database.DatabaseConstructed+=constructed;
  try{copy=db.Wblock();}finally{
   Database.DatabaseConstructed-=constructed;db.WblockMappingAvailable-=capture;db.BeginDeepCloneTranslation-=capture;
   foreach(var fresh in watched)if(!fresh.IsDisposed){fresh.WblockMappingAvailable-=capture;fresh.BeginDeepCloneTranslation-=capture;}
  }
  int expectedCount;
  using(var tr=db.TransactionManager.StartTransaction())expectedCount=((BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForRead)).Cast<ObjectId>().Count();
  using(copy){
   // Entire-database WBLOCK may bypass managed mapping events. Resolve only
   // unambiguous unchanged entity signatures; never guess between duplicates.
   Dictionary<string,List<string>> Index(Database database){
    using var transaction=database.TransactionManager.StartTransaction();var result=new Dictionary<string,List<string>>();
    foreach(ObjectId bid in (BlockTable)transaction.GetObject(database.BlockTableId,OpenMode.ForRead)){
     var block=(BlockTableRecord)transaction.GetObject(bid,OpenMode.ForRead);if(block.IsFromExternalReference)continue;
     var space=bid==SymbolUtilityServices.GetBlockModelSpaceId(database)?"model":block.IsLayout?"layout:"+((Layout)transaction.GetObject(block.LayoutId,OpenMode.ForRead)).LayoutName:"block:"+block.Name;
     foreach(ObjectId id in block){if(transaction.GetObject(id,OpenMode.ForRead) is not Entity entity)continue;
      var row=Row(entity,transaction,space);row.Remove("handle");row.Remove("locked");
      if(entity is DBText or MText or Table)row.Remove("bbox");
      if(entity is MText mt)row["text_style"]=((TextStyleTableRecord)transaction.GetObject(mt.TextStyleId,OpenMode.ForRead)).Name;
      if(entity is Hatch hatch){row["pattern"]=hatch.PatternName;row["pattern_scale"]=hatch.PatternScale;row["pattern_angle"]=hatch.PatternAngle;row["loop_count"]=hatch.NumberOfLoops;}
      var signature=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(row))));
      if(!result.TryGetValue(signature,out var list))result[signature]=list=new();list.Add(entity.Handle.ToString());
     }
    }
    return result;
   }
   var sourceIndex=Index(db);var copyIndex=Index(copy);
   foreach(var pair in sourceIndex)if(pair.Value.Count==1&&copyIndex.TryGetValue(pair.Key,out var matched)&&matched.Count==1)mapping.TryAdd(pair.Value[0],matched[0]);
   using(var tr=copy.TransactionManager.StartTransaction()){
    var bt=(BlockTable)tr.GetObject(copy.BlockTableId,OpenMode.ForRead);
    string Remap(string value){
     if(mapping.TryGetValue(value,out var mapped))return mapped;
     bool exists=false;try{var id=Id(db,value);exists=!id.IsNull&&!id.IsErased;}catch{}
     if(exists)throw new InvalidOperationException("Live entity link cannot be mapped unambiguously: "+value);
     return "0";
    }
    JsonNode Rewrite(JsonNode node){
     var obj=(JsonObject)node;var kind=obj["kind"]?.GetValue<string>()??"";
     void Field(JsonObject parent,string key){
      if(parent[key] is JsonValue val&&val.TryGetValue<string>(out var h))parent[key]=Remap(h);
      else if(parent[key] is JsonArray values)for(int i=0;i<values.Count;i++)if(values[i] is JsonValue item&&item.TryGetValue<string>(out var handle))values[i]=Remap(handle);
     }
     if(kind is "grid_label" or "grid_bubble" or "grid_extension" or "door_window_label")Field(obj,"source");
     if(kind=="opening_schedule")Field(obj,"sources");
     if(kind=="column")Field(obj,"source_axes");
     if(kind is "beam" or "wall_join"){Field(obj,"columns");Field(obj,"related");}
     if(kind=="area_schedule"&&obj["zones"] is JsonArray zones)foreach(var zone in zones)if(zone is JsonObject z){Field(z,"boundary_handle");Field(z,"deduction_handles");}
     return obj;
    }
    foreach(ObjectId bid in bt){var block=(BlockTableRecord)tr.GetObject(bid,OpenMode.ForRead);if(block.IsFromExternalReference)continue;
     foreach(ObjectId id in block){if(tr.GetObject(id,OpenMode.ForRead) is not Entity e)continue;
      var rec=Record(e,tr);if(rec!=null){e.UpgradeOpen();var node=Rewrite(JsonNode.Parse(JsonSerializer.Serialize(rec))!);SetRecord(e,tr,JsonDocument.Parse(node!.ToJsonString()).RootElement);}
      using var owned=e.GetXDataForApplication("ACADMCP_ARCH_H");if(owned!=null){if(!e.IsWriteEnabled)e.UpgradeOpen();e.XData=new ResultBuffer(owned.AsArray().Select(v=>v.TypeCode==1000?new TypedValue(1000,Remap((string)v.Value)):v).ToArray());}
      if(e is Table table){for(int c=0;c<table.Columns.Count;c++)if(table.Cells[0,c].TextString=="来源句柄"){if(!e.IsWriteEnabled)e.UpgradeOpen();for(int r=1;r<table.Rows.Count;r++)if(mapping.TryGetValue(table.Cells[r,c].TextString,out var h))table.Cells[r,c].TextString=h;}}
     }
    }
    tr.Commit();
   }
   copy.SaveAs(path,DwgVersion.AC1032);
  }
  using var verify=new Database(false,true);verify.ReadDwgFile(path,FileOpenMode.OpenForReadAndAllShare,false,"");verify.CloseInput(true);
  using var check=verify.TransactionManager.StartTransaction();var model=(BlockTableRecord)check.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(verify),OpenMode.ForRead);int count=model.Cast<ObjectId>().Count();
  if(count!=expectedCount)throw new InvalidDataException("DWG readback entity count differs");
  return new{ok=true,path,bytes=new FileInfo(path).Length,model_entities=count,reopened=true,remapped_objects=mapping.Count,sha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)))};
 }
 static object Pdf(Database db,JsonElement a){
  Check(db,a);var path=Path.GetFullPath(S(a,"path"));if(File.Exists(path))throw new ArgumentException("Output exists");if(PlotFactory.ProcessPlotState!=ProcessPlotState.NotPlotting)throw new ArgumentException("Plotter busy");
  using var tr=db.TransactionManager.StartTransaction();var ld=(DBDictionary)tr.GetObject(db.LayoutDictionaryId,OpenMode.ForRead);var name=S(a,"layout","Model");if(!ld.Contains(name))throw new ArgumentException("Layout missing");var layout=(Layout)tr.GetObject(ld.GetAt(name),OpenMode.ForRead);
  using var settings=new PlotSettings(layout.ModelType);settings.CopyFrom(layout);var psv=PlotSettingsValidator.Current;var media=settings.CanonicalMediaName;psv.SetPlotConfigurationName(settings,"DWG To PDF.pc3",null);psv.RefreshLists(settings);
  if(!string.IsNullOrEmpty(media)&&psv.GetCanonicalMediaNameList(settings).Contains(media))psv.SetCanonicalMediaName(settings,media);else if(!layout.ModelType)throw new ArgumentException("PDF设备不支持当前布局纸张，请先配置页面设置");
  psv.SetUseStandardScale(settings,true);if(layout.ModelType){psv.SetPlotType(settings,Autodesk.AutoCAD.DatabaseServices.PlotType.Extents);psv.SetStdScaleType(settings,StdScaleType.ScaleToFit);psv.SetPlotCentered(settings,true);}else{psv.SetPlotType(settings,Autodesk.AutoCAD.DatabaseServices.PlotType.Layout);psv.SetStdScaleType(settings,StdScaleType.StdScale1To1);}
  using var pi=new PlotInfo{Layout=layout.ObjectId,OverrideSettings=settings};using var validator=new PlotInfoValidator{MediaMatchingPolicy=MatchingPolicy.MatchEnabled};validator.Validate(pi);
  using(var engine=PlotFactory.CreatePublishEngine()){engine.BeginPlot(null,null);engine.BeginDocument(pi,AcApp.DocumentManager.MdiActiveDocument.Name,null,1,true,path);using var page=new PlotPageInfo();engine.BeginPage(page,pi,true,null);engine.BeginGenerateGraphics(null);engine.EndGenerateGraphics(null);engine.EndPage(null);engine.EndDocument(null);engine.EndPlot(null);}
  var bytes=File.ReadAllBytes(path);if(bytes.Length<5||Encoding.ASCII.GetString(bytes,0,5)!="%PDF-")throw new InvalidDataException("PDF header verification failed");
  return new{ok=true,path,bytes=bytes.Length,header_verified=true,sha256=Convert.ToHexString(SHA256.HashData(bytes))};
 }
}
