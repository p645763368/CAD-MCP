using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.DatabaseServices;
using System.Text.Json;
using Autodesk.Windows;
using AcApp=Autodesk.AutoCAD.ApplicationServices.Core.Application;
[assembly: ExtensionApplication(typeof(CadMcpStatusIcons.Entry))]
[assembly: CommandClass(typeof(CadMcpStatusIcons.Entry))]
namespace CadMcpStatusIcons;
public sealed class Entry:IExtensionApplication {
 static DispatcherTimer? timer;
 static string error="";
 static readonly Dictionary<string,ImageSource> Cache=new();
 static readonly Dictionary<RibbonItem,ImageSource?> Original=new();
 public void Initialize(){AcApp.Idle+=Start;}
 public void Terminate(){AcApp.Idle-=Start;timer?.Stop();foreach(var pair in Original)pair.Key.Image=pair.Value;Original.Clear();}
 static void Start(object? sender,EventArgs e){
  if(ComponentManager.Ribbon==null)return;
  AcApp.Idle-=Start;timer=new DispatcherTimer(DispatcherPriority.Background){Interval=TimeSpan.FromSeconds(.5)};
  timer.Tick+=(_,_)=>SafeRefresh();timer.Start();SafeRefresh();
 }
 static IEnumerable<RibbonItem> Walk(IEnumerable<RibbonItem> items){
  foreach(var item in items){yield return item;if(item is RibbonRowPanel row)foreach(var nested in Walk(row.Items))yield return nested;}
 }
 static void SafeRefresh(){try{Refresh();error="";}catch(System.Exception ex){error=ex.GetType().Name;}}
 [LispFunction("CADMCPICONSINFO")]
 public static ResultBuffer Info(ResultBuffer args){
  var tab=ComponentManager.Ribbon?.Tabs.FirstOrDefault(t=>t.Id=="CAD_MCP_STATUS_2026");
  var count=tab==null?0:tab.Panels.SelectMany(p=>Walk(p.Source.Items)).Count(i=>i.Image!=null);
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(new{icons=count,error})));
 }
 static void Refresh(){
  var tab=ComponentManager.Ribbon?.Tabs.FirstOrDefault(t=>t.Id=="CAD_MCP_STATUS_2026");if(tab==null)return;
  foreach(var item in tab.Panels.SelectMany(p=>Walk(p.Source.Items))){
   string text=item.Text??"";string? kind=null;string color="#A5B5C5";
   if(text.StartsWith("MCP服务")){kind="server";color=text.Contains("运行中")?"#66D9A3":"#A5B5C5";}
   else if(text.StartsWith("客户端")){kind="link";color=text.Contains("已握手")?"#66BFFF":"#A5B5C5";}
   else if(text.StartsWith("AutoCAD")){kind="cad";color=text.Contains("已连接")?"#66D9A3":"#A5B5C5";}
   else if(text.StartsWith("接入：")){kind=text.Contains("暂停")?"off":"on";color=text.Contains("暂停")?"#FFC56D":"#66D9A3";}
   else if(text=="暂停接入"){kind="pause";color="#FFC56D";}
   else if(text=="恢复接入"){kind="play";color="#66D9A3";}
   else if(text=="查看调用历史"){kind="history";color="#66BFFF";}
   else if(text=="暂无调用记录"){kind="clock";}
   else if(text.StartsWith("历史保留")){kind="history";}
   else if(text.Contains("成功")){kind="check";color="#66D9A3";}
   else if(text.Contains("失败")){kind="error";color="#FF8C8C";}
   else if(text.Contains("已拦截")||text.Contains("待核对")){kind="warning";color="#FFC56D";}
   else if(text.Contains("执行中")){kind="clock";color="#66BFFF";}
   if(kind==null)continue;
   if(!Original.ContainsKey(item))Original[item]=item.Image;
   item.Image=Icon(kind,color);item.ShowImage=true;
  }
 }
 static ImageSource Icon(string kind,string color){
  string key=kind+color;if(Cache.TryGetValue(key,out var cached))return cached;
  var brush=new SolidColorBrush((Color)ColorConverter.ConvertFromString(color));brush.Freeze();
  var pen=new Pen(brush,1.4){StartLineCap=PenLineCap.Round,EndLineCap=PenLineCap.Round,LineJoin=PenLineJoin.Round};pen.Freeze();
  var drawing=new DrawingGroup();
  using(var d=drawing.Open()){
   d.DrawRectangle(Brushes.Transparent,null,new Rect(0,0,16,16));
   void Path(string p)=>d.DrawGeometry(null,pen,Geometry.Parse(p));
   switch(kind){
    case "server":d.DrawRoundedRectangle(null,pen,new Rect(2,2,12,5),1,1);d.DrawRoundedRectangle(null,pen,new Rect(2,9,12,5),1,1);d.DrawEllipse(brush,null,new Point(4.5,4.5),.8,.8);d.DrawEllipse(brush,null,new Point(4.5,11.5),.8,.8);Path("M8,4.5 L11.5,4.5 M8,11.5 L11.5,11.5");break;
    case "link":Path("M6,10 L10,6 M6.5,5.5 L8,4 C11,1 15,5 12,8 L10.5,9.5 M5.5,6.5 L4,8 C1,11 5,15 8,12 L9.5,10.5");break;
    case "cad":Path("M2,13 L8,2 L14,13 Z M5,9 L11,9 M8,2 L8,5");break;
    case "on":case "off":d.DrawRoundedRectangle(null,pen,new Rect(1,4,14,8),4,4);d.DrawEllipse(brush,null,new Point(kind=="on"?11:5,8),2.5,2.5);break;
    case "pause":d.DrawRoundedRectangle(brush,null,new Rect(3,3,3.3,10),.6,.6);d.DrawRoundedRectangle(brush,null,new Rect(9.7,3,3.3,10),.6,.6);break;
    case "play":d.DrawGeometry(brush,null,Geometry.Parse("M4,2.5 L13,8 L4,13.5 Z"));break;
    case "history":Path("M5,3 L13,3 M5,8 L13,8 M5,13 L13,13");foreach(double y in new[]{3d,8d,13d})d.DrawEllipse(brush,null,new Point(2,y),.8,.8);break;
    case "clock":d.DrawEllipse(null,pen,new Point(8,8),6,6);Path("M8,4 L8,8 L11,10");break;
    case "check":d.DrawEllipse(null,pen,new Point(8,8),6,6);Path("M4.5,8 L7,10.5 L11.5,5.5");break;
    case "error":d.DrawEllipse(null,pen,new Point(8,8),6,6);Path("M5.5,5.5 L10.5,10.5 M10.5,5.5 L5.5,10.5");break;
    case "warning":Path("M8,1.5 L15,14 L1,14 Z M8,5.5 L8,9");d.DrawEllipse(brush,null,new Point(8,11.5),.7,.7);break;
   }
  }
  drawing.Freeze();var image=new DrawingImage(drawing);image.Freeze();Cache[key]=image;return image;
 }
}
