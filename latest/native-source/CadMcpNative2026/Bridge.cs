using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.EditorInput;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using System.Text.Json;

namespace CadMcpNative;
public class Bridge
{
    public const string Version = "1.0.0";
    [LispFunction("MCPNATIVE2026")]
    public static ResultBuffer Run(ResultBuffer args)
    {
        object result;
        try {
            var a=JsonDocument.Parse((string)args.AsArray()[0].Value).RootElement;
            string op=a.GetProperty("op").GetString()!;
            if(op=="ping") result=new {ok=true,version=Version};
            else {
                var doc=AcApp.DocumentManager.MdiActiveDocument ?? throw new InvalidOperationException("No active document");
                if(!string.Equals(doc.Name,a.GetProperty("document").GetString(),StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Active document changed; request refused");
                using var locked=doc.LockDocument();
                result=op switch {"wipeout"=>Wipeout(a,doc.Database),"trace"=>Trace(a,doc.Database,doc.Editor),"chspace"=>ChangeSpace(a,doc.Database),_=>throw new ArgumentException("Unknown operation")};
            }
        } catch(System.Exception e) {result=new {ok=false,error=e.Message};}
        return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(result)));
    }
    static string Str(JsonElement a,string key,string fallback="")=>a.TryGetProperty(key,out var v)?v.GetString()??fallback:fallback;
    static double Num(JsonElement a,string key) {var n=a.GetProperty(key).GetDouble();if(!double.IsFinite(n))throw new ArgumentException("Nonfinite coordinate");return n;}
    static ObjectId Id(Database db,string handle)=>db.GetObjectId(false,new Handle(Convert.ToInt64(handle,16)),0);
    static string Layer(JsonElement a,Database db,Transaction tr) {
        var name=Str(a,"layer");
        if(name=="")return ((LayerTableRecord)tr.GetObject(db.Clayer,OpenMode.ForRead)).Name;
        var lt=(LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead);
        if(!lt.Has(name))throw new ArgumentException("Layer does not exist: "+name);
        if(((LayerTableRecord)tr.GetObject(lt[name],OpenMode.ForRead)).IsLocked)throw new ArgumentException("Layer is locked");
        return name;
    }
    static object Wipeout(JsonElement a,Database db) {
        using var tr=db.TransactionManager.StartTransaction();
        var layer=Layer(a,db,tr);
        var pts=new Point2dCollection();
        foreach(var row in a.GetProperty("points").EnumerateArray())pts.Add(new Point2d(row[0].GetDouble(),row[1].GetDouble()));
        if(pts.Count<3)throw new ArgumentException("At least three vertices required");
        if(!pts[0].IsEqualTo(pts[pts.Count-1]))pts.Add(pts[0]);
        var ms=(BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForWrite);
        using var ent=new Autodesk.AutoCAD.DatabaseServices.Wipeout();
        ent.SetDatabaseDefaults(db); ent.SetFrom(pts,Vector3d.ZAxis); ent.Layer=layer;
        var id=ms.AppendEntity(ent);tr.AddNewlyCreatedDBObject(ent,true);
        var order=(DrawOrderTable)tr.GetObject(ms.DrawOrderTableId,OpenMode.ForWrite);
        order.MoveToTop(new ObjectIdCollection(new[]{id}));
        string h=id.Handle.ToString();tr.Commit();
        return new {ok=true,handle=h,layer,representation="native_WIPEOUT",draw_order="top"};
    }
    static object Trace(JsonElement a,Database db,Editor ed) {
        if(!db.TileMode && Convert.ToInt32(AcApp.GetSystemVariable("CVPORT"))==1)
            throw new ArgumentException("boundary_trace requires model space");
        if(Math.Abs(Num(a,"tolerance")-1e-9)>1e-12)
            throw new ArgumentException("Native trace currently supports exact closed boundaries only; custom gap tolerance is not implemented");
        using var tr=db.TransactionManager.StartTransaction();
        var outputLayer=Layer(a,db,tr);var filter=Str(a,"layer");
        var hidden=new List<(LayerTableRecord,bool)>();
        using var view=ed.GetCurrentView();
        var created=new List<Entity>();
        try {
            if(filter!="")foreach(ObjectId id in (LayerTable)tr.GetObject(db.LayerTableId,OpenMode.ForRead)) {
                var l=(LayerTableRecord)tr.GetObject(id,OpenMode.ForWrite);
                hidden.Add((l,l.IsOff));l.IsOff=!string.Equals(l.Name,filter,StringComparison.OrdinalIgnoreCase);
            }
            var ms=(BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db),OpenMode.ForRead);
            Extents3d? box=null;
            foreach(ObjectId id in ms) {
                var e=(Entity)tr.GetObject(id,OpenMode.ForRead);
                if(filter!=""&&!string.Equals(e.Layer,filter,StringComparison.OrdinalIgnoreCase))continue;
                if(e is not Curve)continue;
                var ext=e.GeometricExtents;
                if(box is null)box=ext;else {var b=box.Value;b.AddExtents(ext);box=b;}
            }
            if(box is null)throw new ArgumentException("No curve geometry to trace");
            var lo=box.Value.MinPoint;var hi=box.Value.MaxPoint;
            using(var v=new ViewTableRecord()) {
                v.ViewDirection=Vector3d.ZAxis;v.Target=Point3d.Origin;v.ViewTwist=0;
                v.CenterPoint=new Point2d((lo.X+hi.X)/2,(lo.Y+hi.Y)/2);
                v.Width=Math.Max(hi.X-lo.X,1)*1.2;v.Height=Math.Max(hi.Y-lo.Y,1)*1.2;
                ed.SetCurrentView(v);ed.Regen();
            }
            var seed=new Point3d(Num(a,"x"),Num(a,"y"),0).TransformBy(ed.CurrentUserCoordinateSystem.Inverse());
            using var found=ed.TraceBoundary(seed,true);
            foreach(DBObject obj in found) {
                if(obj is not Polyline pl || !pl.Closed){obj.Dispose();throw new ArgumentException("Trace returned a non-closed/non-polyline result");}
                created.Add(pl);
            }
            if(created.Count==0)throw new ArgumentException("No closed region encloses seed point");
            var polys=created.Cast<Polyline>().OrderByDescending(p=>p.Area).ToList();
            var area=polys[0].Area-polys.Skip(1).Sum(p=>p.Area);
            if(area<=0)throw new ArgumentException("Invalid nested-boundary area");
            ms.UpgradeOpen();var handles=new List<string>();
            foreach(var p in polys){p.SetDatabaseDefaults(db);p.Layer=outputLayer;var id=ms.AppendEntity(p);tr.AddNewlyCreatedDBObject(p,true);handles.Add(id.Handle.ToString());}
            foreach(var (l,off) in hidden)l.IsOff=off;
            tr.Commit();
            return new {ok=true,handle=handles[0],handles,islands=handles.Skip(1).ToArray(),area,closed=true,mode="native_TraceBoundary",gap_tolerance_supported=false};
        } finally {
            foreach(var (l,off) in hidden)if(!l.IsDisposed&&!l.IsErased)try{l.IsOff=off;}catch{}
            try{ed.SetCurrentView(view);ed.Regen();}catch{}
            foreach(var p in created)if(p.ObjectId.IsNull)p.Dispose();
        }
    }
    static object ChangeSpace(JsonElement a,Database db) {
        using var tr=db.TransactionManager.StartTransaction();
        var v=(Viewport)tr.GetObject(Id(db,Str(a,"viewport_handle")),OpenMode.ForRead);
        if(v.Number==1)throw new ArgumentException("Overall paper viewport is not a model viewport");
        if(v.PerspectiveOn || !v.ViewDirection.GetNormal().IsEqualTo(Vector3d.ZAxis,new Tolerance(1e-9,1e-9)) || Math.Abs(v.TwistAngle)>1e-9 || v.NonRectClipOn)
            throw new ArgumentException("Only untwisted, orthographic top-view rectangular viewports are supported");
        var dir=Str(a,"direction");if(dir!="to_paper"&&dir!="to_model")throw new ArgumentException("Invalid direction");
        var model=SymbolUtilityServices.GetBlockModelSpaceId(db);var paper=v.OwnerId;
        bool toPaper=dir=="to_paper";var src=toPaper?model:paper;var dst=toPaper?paper:model;
        double scale=v.CustomScale;if(!double.IsFinite(scale)||scale<=0)throw new ArgumentException("Invalid viewport scale");
        var center=new Point3d(v.ViewTarget.X+v.ViewCenter.X,v.ViewTarget.Y+v.ViewCenter.Y,v.ViewTarget.Z);
        var matrix=Matrix3d.Displacement(v.CenterPoint-Point3d.Origin)*Matrix3d.Scaling(scale,Point3d.Origin)*Matrix3d.Displacement(Point3d.Origin-center);
        if(!toPaper)matrix=matrix.Inverse();
        var ids=new ObjectIdCollection();
        foreach(var item in a.GetProperty("handles").EnumerateArray()) {
            var id=Id(db,item.GetString()!);if(ids.Contains(id))throw new ArgumentException("Duplicate handle");
            var e=(Entity)tr.GetObject(id,OpenMode.ForRead);
            if(e.OwnerId!=src)throw new ArgumentException("Entity is not in the expected source space");
            if(e is not Line && e is not Circle && e is not Arc && e is not Polyline && e is not DBText && e is not MText && e is not BlockReference)
                throw new ArgumentException("Unsupported entity type for space change: "+e.GetType().Name);
            if(e.Annotative==AnnotativeStates.True)throw new ArgumentException("Annotative entities are not supported");
            if(((LayerTableRecord)tr.GetObject(e.LayerId,OpenMode.ForRead)).IsLocked)throw new ArgumentException("Entity layer is locked");
            ids.Add(id);
        }
        if(ids.Count==0||ids.Count>32)throw new ArgumentException("Provide 1 to 32 entities per call");
        var mapping=new IdMapping();db.DeepCloneObjects(ids,dst,mapping,false);
        var moved=new List<object>();
        foreach(ObjectId id in ids) {
            var target=mapping[id].Value;var copy=(Entity)tr.GetObject(target,OpenMode.ForWrite);
            copy.TransformBy(matrix);
            var original=(Entity)tr.GetObject(id,OpenMode.ForWrite);original.Erase();
            moved.Add(new {old_handle=id.Handle.ToString(),handle=target.Handle.ToString()});
        }
        tr.Commit();return new {ok=true,moved,scale=toPaper?scale:1/scale,direction=dir,dimensions_supported=false,atomic=true};
    }
}
