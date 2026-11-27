using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Threading;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Windows;
using Autodesk.Windows;
using AcApp=Autodesk.AutoCAD.ApplicationServices.Core.Application;
using WButton=System.Windows.Controls.Button;
using WOrientation=System.Windows.Controls.Orientation;
[assembly: ExtensionApplication(typeof(CadMcpStatus.Entry))]
[assembly: CommandClass(typeof(CadMcpStatus.Entry))]
namespace CadMcpStatus;

public sealed class HistoryRow {
 public string Id {get;set;}="";
 public string Tool {get;set;}="";
 public string Time {get;set;}="";
 public string State {get;set;}="";
 public string Duration {get;set;}="";
 public string Process {get;set;}="";
 public string Detail {get;set;}="";
 public DateTimeOffset Started {get;set;}
}
sealed class Session {
 public string Id=""; public int Pid; public long Seen;
 public bool Running, Initialized, CadConnected, Enabled;
 public string Transport="stdio", Build="";
 public List<HistoryRow> Rows=new();
}
sealed class ActionCommand : ICommand {
 readonly Action action; public ActionCommand(Action action)=>this.action=action;
 public event EventHandler? CanExecuteChanged {add {} remove {}}
 public bool CanExecute(object? p)=>true; public void Execute(object? p)=>action();
}

public sealed class Entry:IExtensionApplication {
 const string TabId="CAD_MCP_STATUS_2026";
 static readonly object Sync=new();
 static readonly Dictionary<string,Session> Sessions=new();
 static readonly int CadPid=Environment.ProcessId;
 static readonly string PipeName="CadMcpStatus-"+WindowsIdentity.GetCurrent().User!.Value.Replace("-","")+"-"+CadPid;
 static bool Allowed=true, Hidden=false;
 static CancellationTokenSource? Stop;
 static DispatcherTimer? Timer;
 static RibbonTab? Tab;
 static RibbonLabel? ServiceLabel,ClientLabel,CadLabel,GateLabel,RecentLabel,Recent2Label;
 static RibbonButton? ToggleButton;
 static PaletteSet? Palette;
 static DataGrid? Grid;
 static TextBlock? HistoryStatus;
 static string HistorySignature="";
 static string Error="";

 public void Initialize() {
  Stop=new(); _=Task.Run(()=>Listen(Stop.Token));
  AcApp.Idle+=OnIdle;
 }
 public void Terminate() {
  Stop?.Cancel();Timer?.Stop();AcApp.Idle-=OnIdle;
  try {if(Tab!=null)ComponentManager.Ribbon?.Tabs.Remove(Tab);Palette?.Dispose();}catch {}
 }
 static void OnIdle(object? sender,EventArgs e) {
  if(ComponentManager.Ribbon==null)return;
  AcApp.Idle-=OnIdle;EnsureRibbon();
  Timer=new DispatcherTimer(DispatcherPriority.Background){Interval=TimeSpan.FromSeconds(1)};
  Timer.Tick+=(_,_)=> {try {EnsureRibbon();Refresh();}catch(System.Exception ex){Error=ex.GetType().Name;}};
  Timer.Start();Refresh();
 }
 static void EnsureRibbon() {
  var ribbon=ComponentManager.Ribbon;
  if(ribbon==null||Hidden)return;
  var existing=ribbon.Tabs.FirstOrDefault(t=>t.Id==TabId);
  if(existing!=null){Tab=existing;return;}
  Tab=new RibbonTab{Id=TabId,Title="CAD-MCP · 未连接"};
  var state=new RibbonPanelSource{Title="连接状态"};
  var rows=new RibbonRowPanel();
  ServiceLabel=new RibbonLabel{Text="MCP服务：等待连接"};
  ClientLabel=new RibbonLabel{Text="客户端：未连接"};
  CadLabel=new RibbonLabel{Text="AutoCAD：等待确认"};
  rows.Items.Add(ServiceLabel);rows.Items.Add(new RibbonRowBreak());rows.Items.Add(ClientLabel);rows.Items.Add(new RibbonRowBreak());rows.Items.Add(CadLabel);
  state.Items.Add(rows);Tab.Panels.Add(new RibbonPanel{Source=state});
  var control=new RibbonPanelSource{Title="工具接入"};var controlRows=new RibbonRowPanel();
  GateLabel=new RibbonLabel{Text="接入：开启"};
  ToggleButton=new RibbonButton{Text="暂停接入",ShowText=true,Size=RibbonItemSize.Standard,CommandHandler=new ActionCommand(()=>SetAllowed(!Allowed))};
  var history=new RibbonButton{Text="查看调用历史",ShowText=true,Size=RibbonItemSize.Standard,CommandHandler=new ActionCommand(ShowHistory)};
  controlRows.Items.Add(GateLabel);controlRows.Items.Add(new RibbonRowBreak());controlRows.Items.Add(ToggleButton);controlRows.Items.Add(new RibbonRowBreak());controlRows.Items.Add(history);
  control.Items.Add(controlRows);Tab.Panels.Add(new RibbonPanel{Source=control});
  var recent=new RibbonPanelSource{Title="最近调用"};var recentRows=new RibbonRowPanel();
  RecentLabel=new RibbonLabel{Text="暂无调用记录"};Recent2Label=new RibbonLabel{Text="历史保留最近200条"};
  recentRows.Items.Add(RecentLabel);recentRows.Items.Add(new RibbonRowBreak());recentRows.Items.Add(Recent2Label);
  recent.Items.Add(recentRows);Tab.Panels.Add(new RibbonPanel{Source=recent});
  ribbon.Tabs.Add(Tab);
 }
 static void SetAllowed(bool allowed) {lock(Sync)Allowed=allowed;Refresh();}
 static (List<Session> live,List<HistoryRow> rows) Snapshot() {
  lock(Sync) {
   var now=Environment.TickCount64;
   var live=Sessions.Values.Where(s=>now-s.Seen<5000&&s.Running).ToList();
   var rows=Sessions.Values.SelectMany(s=>s.Rows.Select(r=>now-s.Seen>=5000&&r.State=="执行中" ? new HistoryRow{Id=r.Id,Tool=r.Tool,Time=r.Time,State="待核对",Duration="—",Process=r.Process,Started=r.Started,Detail="服务心跳中断，请核对CAD结果"} : r)).OrderByDescending(r=>r.Started).Take(200).ToList();
   return(live,rows);
  }
 }
 static void Refresh() {
  var (live,rows)=Snapshot();int clients=live.Count(s=>s.Initialized&&s.Transport=="stdio"),cad=live.Count(s=>s.CadConnected);
  var inflight=rows.Count(r=>r.State=="执行中");
  bool acknowledged=live.All(s=>s.Enabled==Allowed);
  var gate=Allowed?"开启":"暂停";
  if(!acknowledged&&live.Count>0)gate+="（同步中）";
  if(Tab!=null)Tab.Title="CAD-MCP · "+(!Allowed?"已暂停":clients>0?"已连接":"未连接");
  if(ServiceLabel!=null)ServiceLabel.Text=live.Count>0?$"MCP服务：运行中（{live.Count}）":"MCP服务：未连接";
  if(ClientLabel!=null)ClientLabel.Text=clients>0?$"客户端：已握手（{clients}）":"客户端：未连接";
  if(CadLabel!=null)CadLabel.Text=cad>0?"AutoCAD：已连接":"AutoCAD：等待MCP连接";
  if(GateLabel!=null)GateLabel.Text="接入："+gate+(inflight>0?$" · {inflight}项执行中":"");
  if(ToggleButton!=null)ToggleButton.Text=Allowed?"暂停接入":"恢复接入";
  if(RecentLabel!=null)RecentLabel.Text=rows.Count>0?$"{rows[0].Time}  {rows[0].Tool}  {rows[0].State}":"暂无调用记录";
  if(Recent2Label!=null)Recent2Label.Text=rows.Count>1?$"{rows[1].Time}  {rows[1].Tool}  {rows[1].State}":"历史保留最近200条";
  if(HistoryStatus!=null)HistoryStatus.Text=$"接入：{gate}    活跃服务：{live.Count}    客户端握手：{clients}    执行中：{inflight}\n暂停后拦截新操作；已开始的操作继续完成。记录仅保存在本次CAD会话内。";
  if(Grid!=null&&Palette?.Visible==true) {
   var signature=string.Join("|",rows.Select(r=>r.Id+":"+r.State+":"+r.Duration));
   if(signature!=HistorySignature){Grid.ItemsSource=rows;HistorySignature=signature;}
  }
 }
 static void ShowHistory() {
  if(Palette==null) {
   Palette=new PaletteSet("CAD-MCP 调用历史",new Guid("4568623f-b864-44b6-a353-a8c1c1fc4731")) {
    Style=PaletteSetStyles.ShowCloseButton|PaletteSetStyles.ShowAutoHideButton|PaletteSetStyles.ShowPropertiesMenu,
    MinimumSize=new System.Drawing.Size(550,240),Size=new System.Drawing.Size(860,360)
   };
   var panel=new DockPanel{LastChildFill=true,Margin=new Thickness(12)};
   HistoryStatus=new TextBlock{Margin=new Thickness(0,0,0,12),TextWrapping=TextWrapping.Wrap};DockPanel.SetDock(HistoryStatus,Dock.Top);panel.Children.Add(HistoryStatus);
   Grid=new DataGrid{AutoGenerateColumns=false,IsReadOnly=true,CanUserAddRows=false,CanUserDeleteRows=false,HeadersVisibility=DataGridHeadersVisibility.Column,SelectionMode=DataGridSelectionMode.Single};
   foreach(var (label,path,width) in new[]{("时间","Time",85d),("工具","Tool",230d),("结果","State",80d),("耗时","Duration",90d),("服务PID","Process",80d),("备注","Detail",180d)})
    Grid.Columns.Add(new DataGridTextColumn{Header=label,Binding=new System.Windows.Data.Binding(path),Width=new DataGridLength(width)});
   panel.Children.Add(Grid);Palette.AddVisual("最近调用",panel);
  }
  HistorySignature="";Palette.Visible=true;Refresh();
 }

 static async Task Listen(CancellationToken token) {
  while(!token.IsCancellationRequested) {
   try {
    using var pipe=new NamedPipeServerStream(PipeName,PipeDirection.InOut,4,PipeTransmissionMode.Message,PipeOptions.Asynchronous|PipeOptions.CurrentUserOnly,8192,8192);
    await pipe.WaitForConnectionAsync(token);
    using var timeout=CancellationTokenSource.CreateLinkedTokenSource(token);timeout.CancelAfter(2000);
    // Bound incoming data before JSON parsing.
    var buffer=new byte[8192];using var memory=new MemoryStream();
    do {
     int count=await pipe.ReadAsync(buffer,timeout.Token);if(count==0)break;
     memory.Write(buffer,0,count);if(memory.Length>200000)throw new InvalidDataException("oversize");
    } while(!pipe.IsMessageComplete);
    var data=JsonDocument.Parse(memory.ToArray());Accept(data.RootElement);
    bool allowed;lock(Sync)allowed=Allowed;
    var reply=Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new{protocol=1,enabled=allowed,cad_pid=CadPid})+"\n");
    await pipe.WriteAsync(reply,timeout.Token);await pipe.FlushAsync(timeout.Token);
   } catch(OperationCanceledException) {if(token.IsCancellationRequested)return;}
   catch(System.Exception ex) {Error=ex.GetType().Name;await Task.Delay(200,token).ContinueWith(_=>{});}
  }
 }
 static string Str(JsonElement e,string name,string fallback="")=>e.TryGetProperty(name,out var x)&&x.ValueKind==JsonValueKind.String?x.GetString()??fallback:fallback;
 static bool Bool(JsonElement e,string name)=>e.TryGetProperty(name,out var x)&&x.ValueKind==JsonValueKind.True;
 static void Accept(JsonElement data) {
  if(data.GetProperty("protocol").GetInt32()!=1)return;
  var target=data.GetProperty("cad_pid").GetInt32();if(target!=0&&target!=CadPid)return;
  var id=Str(data,"session");if(id.Length!=32)return;
  var pid=data.GetProperty("pid").GetInt32();if(pid<=0)return;
  var s=new Session{Id=id,Pid=pid,Seen=Environment.TickCount64,Running=Bool(data,"running"),Initialized=Bool(data,"client_initialized"),CadConnected=Bool(data,"cad_connected")&&target==CadPid,Enabled=Bool(data,"enabled"),Build=Str(data,"build"),Transport=Str(data,"transport")};
  foreach(var key in new[]{"inflight","history"}) {
   if(!data.TryGetProperty(key,out var list)||list.ValueKind!=JsonValueKind.Array)continue;
   foreach(var row in list.EnumerateArray().Take(200)) {
    if(!DateTimeOffset.TryParse(Str(row,"started"),out var date))continue;
    double ms=row.TryGetProperty("elapsed_ms",out var elapsed)?elapsed.GetDouble():0;
    s.Rows.Add(new HistoryRow{Id=id+Str(row,"id"),Tool=Str(row,"tool"),Time=date.ToLocalTime().ToString("HH:mm:ss"),Started=date,State=Str(row,"state"),Duration=Str(row,"state")=="执行中"?"…":$"{ms/1000:0.000} s",Process=pid.ToString(),Detail=Str(row,"error_type")});
   }
  }
  lock(Sync) {
   Sessions[id]=s;
   while(Sessions.Count>8)Sessions.Remove(Sessions.Values.OrderBy(x=>x.Seen).First().Id);
  }
 }
 [CommandMethod("CADMCPSTATUS",CommandFlags.Session)] public void Show() {Hidden=false;EnsureRibbon();if(Tab!=null)Tab.IsActive=true;Refresh();}
 [CommandMethod("CADMCPHISTORY",CommandFlags.Session)] public void History()=>ShowHistory();
 [CommandMethod("CADMCPHIDE",CommandFlags.Session)] public void Hide() {Hidden=true;if(Tab!=null)ComponentManager.Ribbon?.Tabs.Remove(Tab);Tab=null;if(Palette!=null)Palette.Visible=false;}
 [LispFunction("CADMCPSTATUSINFO")]
 public static ResultBuffer Info(ResultBuffer args) {
  var (live,rows)=Snapshot();var value=new{ok=true,cad_pid=CadPid,tab_visible=ComponentManager.Ribbon?.Tabs.Any(t=>t.Id==TabId)==true,enabled=Allowed,live_services=live.Count,clients=live.Count(s=>s.Initialized&&s.Transport=="stdio"),cad_connected=live.Any(s=>s.CadConnected),history_count=rows.Count,history=rows.Take(10),history_visible=Palette?.Visible==true,builds=live.Select(s=>s.Build),error=Error};
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,JsonSerializer.Serialize(value)));
 }
 [LispFunction("CADMCPSTATUSACTION")]
 public static ResultBuffer Action(ResultBuffer args) {
  var action=args.AsArray().FirstOrDefault().Value as string;
  if(action=="pause")SetAllowed(false);else if(action=="resume")SetAllowed(true);else if(action=="history")ShowHistory();else throw new ArgumentException("pause/resume/history");
  return new ResultBuffer(new TypedValue((int)LispDataType.Text,"ok"));
 }
}
