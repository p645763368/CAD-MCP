"""Generate README workflow illustrations. Requires Pillow and a Chinese font.
Usage: python scripts/render_readme_demos.py --font C:/Windows/Fonts/msyh.ttc
Synthetic diagrams only; never connects to AutoCAD or opens project drawings.
"""
from pathlib import Path
import argparse, math
from PIL import Image, ImageDraw, ImageFont
parser=argparse.ArgumentParser()
parser.add_argument('--only', nargs='*', help='Render selected scene names')
parser.add_argument('--font', default='C:/Windows/Fonts/msyh.ttc')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'latest/docs/media';OUT.mkdir(parents=True,exist_ok=True)
FONT={n:ImageFont.truetype(args.font,n) for n in (14,16,18,20,24,30)}
BG='#101923'; PANEL='#192633'; GRID='#20303d'; WHITE='#edf4fa'; MUTED='#97adbf'; GREEN='#63dca3'; BLUE='#66b9ff'; ORANGE='#ffca78'
SCENES=[
 ('drawing-info','先了解图纸',['打开图纸','读取信息','查看结果'],['读取图纸信息','图纸：示例平面.dwg','单位：毫米','图层：6 个','模型实体：48 个','保存状态：有未保存修改']),
 ('door-layers','按规则整理图层',['核对选中门线','修改所属图层','检查修改数量'],['门线图层整理','目标：A-SingleDoor','对象：选中的 3 条门线','原图层：A-DOOR','修改后：A-SingleDoor','已核对：3 / 3 条']),
 ('dimension-chain','标注尺寸',['指定测量点','生成水平尺寸链','核对尺寸数值'],['水平尺寸链','图纸单位：毫米','测量点：4 个','分段：3000 / 2400 / 3600','总长：9000 mm','结果：3 段尺寸']),
 ('room-detection','识别房间',['读取墙线','识别闭合区域','查看候选房间'],['房间识别结果','闭合候选：3 个','面积：12 / 18 / 15 m²','待核对：右下方缺口','下一步：确认用途与名称','房间名称尚未写入']),
 ('viewport-scale','检查布局',['选定普通视口','设置 1:100','锁定并核对'],['布局视口设置','对象：指定普通视口','原比例：1:150','目标比例：1:100','视口状态：已锁定','其他视口：保留原设置']),
 ('geometry-rounding','整理图纸碎数',['预览实际几何','检查连接与位移','归整并核对'],['碎数整理结果','网格：1 mm','位移上限：0.01 mm','整理前：2999.997 mm','整理后：3000 mm','接点保持连接 · Z保持原值']),
 ('parking-layout','停车位排布',['确认边界与柱墙','预览避让结果','连续编号与统计'],['车位排布结果','车位：2500 × 5000 mm','通道：6000 mm','候选：12 个','柱位冲突：排除 2 个','采用：10 个 · 连续编号']),
 ('door-window-schedule','门窗型号与数量',['读取块属性','同规格分配型号','生成数量明细'],['门窗型号统计','读取：3 樘门、2 樘窗','同规格共用一个型号','M01：900 × 2100 · 2 樘','M02：1200 × 2100 · 1 樘','C01：1500 × 1500 · 2 樘']),
 ('drawing-delivery','检查与交付',['检查图纸与依赖','核对交付内容','输出并验证文件'],['本次交付结果','检查：通过 · 读取完整','DWG：副本保存并核验','PDF：指定布局输出','附带：外部依赖清单','原图保留 · 文件已核验'])]

def text(d,xy,s,size=18,color=WHITE): d.text(xy,s,font=FONT[size],fill=color)
def line(d,points,color=GREEN,width=3):d.line(points,fill=color,width=width)
def door_leaf(d,x,color=ORANGE):
 # Hinge sits on the left jamb; the leaf opens inward by 90 degrees.
 hinge=x-18; y=278; width=36
 line(d,[(hinge,y),(hinge,y-width)],color,3)
 d.arc((hinge-width,y-width,hinge+width,y+width),270,360,fill=MUTED,width=1)
 d.ellipse((hinge-2,y-2,hinge+2,y+2),fill=color)

def roomplan(d):
 for x in range(40,630,25):line(d,[(x,135),(x,430)],GRID,1)
 for y in range(135,440,25):line(d,[(40,y),(620,y)],GRID,1)
 d.rectangle((100,175,550,390),outline=GREEN,width=2)
 d.rectangle((106,181,544,384),outline=GREEN,width=2)
 for y in (278,286):line(d,[(106,y),(544,y)],GREEN,2)
 for x in (250,400):
  for dx in (-3,3):line(d,[(x+dx,181),(x+dx,278)],GREEN,2)
 for x in (180,330,480):
  d.rectangle((x-18,276,x+18,288),fill=BG)
  for jamb in (x-18,x+18):line(d,[(jamb,278),(jamb,286)],GREEN,2)
  door_leaf(d,x)
 text(d,(300,330),'走道',18,MUTED)

def render(idx,frame):
 name,title,stages,labels=SCENES[idx]
 phase=frame//12;progress=(frame%12)/11
 im=Image.new('RGB',(960,540),BG);d=ImageDraw.Draw(im)
 text(d,(30,20),'CAD-MCP',20,BLUE);text(d,(178,17),title,30)
 d.rounded_rectangle((805,22,930,53),radius=10,fill=PANEL);text(d,(824,28),'操作示意',16,MUTED)
 for j,step in enumerate(stages):
  x=30+j*310;c=BLUE if j==phase else MUTED
  d.ellipse((x,78,x+24,102),fill=c if j<=phase else PANEL)
  text(d,(x+7,79),str(j+1),14,BG if j<=phase else MUTED)
  text(d,(x+35,76),step,18,c)
 d.rounded_rectangle((650,130,930,446),radius=14,fill=PANEL)
 text(d,(670,151),labels[0],20)
 for j,label in enumerate(labels[1:]):
  visible=phase==2 or (phase==1 and j<1+int(progress*5))
  if visible:text(d,(670,200+j*40),label,16,GREEN if j==4 else WHITE)
 if phase==0:text(d,(670,207),'等待开始…',18,MUTED)
 if idx in (0,1):
  roomplan(d)
  if idx==0 and phase>=1:
   y=160+int((frame%12)/11*245);line(d,[(80,y),(570,y)],BLUE,2)
   if phase==2:
    for k,(x,y) in enumerate([(175,225),(325,225),(475,225)]):text(d,(x-30,y),'房间 '+str(k+1),16,MUTED)
  if idx==1:
   for x in (180,330,480):
    col=BLUE if phase>=1 else ORANGE
    door_leaf(d,x,col)
    if phase==0:
     d.rectangle((x-25,235,x-11,284),outline=BLUE,width=1)
   text(d,(130,408),'A-SingleDoor' if phase>=1 else '已选中 3 条门短线',18,BLUE if phase>=1 else ORANGE)
 elif idx==2:
  xs=[80,240,368,560]
  for x in xs:
   line(d,[(x,270),(x,405)],GREEN,3);d.ellipse((x-5,266,x+5,276),fill=BLUE)
  line(d,[(80,350),(560,350)],GREEN,4)
  for j,x in enumerate(xs):text(d,(x-12,415),'P'+str(j+1),16,MUTED)
  if phase>=1:
   count=3 if phase==2 else 1+int(progress*2)
   for j in range(count):
    a,b=xs[j:j+2];line(d,[(a,255),(a,208)],BLUE,1);line(d,[(b,255),(b,208)],BLUE,1)
    line(d,[(a,225),(b,225)],BLUE,2)
    for v in (a,b):line(d,[(v-5,231),(v+5,219)],BLUE,2)
    text(d,((a+b)//2-25,194),['3000','2400','3600'][j],18)
 elif idx==3:
  boxes=[(80,175,270,285),(290,175,560,285),(80,305,310,415)]
  for j,box in enumerate(boxes):
   if phase>=1 and (phase==2 or j<=int(progress*3)):
    d.rectangle(box,fill=['#1d5148','#1b465d','#494460'][j])
    text(d,(box[0]+22,box[1]+25),'候选 '+str(j+1),18)
    text(d,(box[0]+22,box[1]+57),['12 m²','18 m²','15 m²'][j],18,GREEN)
   d.rectangle(box,outline=GREEN,width=3)
  line(d,[(340,415),(340,305),(560,305),(560,415),(485,415)],GREEN,3)
  line(d,[(340,415),(420,415)],GREEN,3)
  if phase>=1:
   d.ellipse((410,390,495,437),outline=ORANGE,width=2);text(d,(365,342),'边界缺口',18,ORANGE)
 elif idx==4:
  d.rectangle((95,143,570,430),fill='#edf1f4')
  d.rectangle((118,160,547,409),outline='#5a6e7c',width=2)
  d.rectangle((140,180,405,380),fill=BG,outline=BLUE,width=3)
  # Enlargement remains clipped within the selected viewport.
  factor=1 if phase==0 else 1+0.5*(progress if phase==1 else 1)
  cx,cy=273,280;w,h=140*factor,95*factor
  d.rectangle((cx-w/2,cy-h/2,cx+w/2,cy+h/2),outline=GREEN,width=3)
  line(d,[(cx,cy-h/2),(cx,cy+h/2)],GREEN,2)
  line(d,[(cx-w/2,cy),(cx+w/2,cy)],GREEN,2)
  d.rectangle((430,190,526,280),fill=BG,outline=MUTED,width=2)
  text(d,(445,218),'保留',16,MUTED)
  text(d,(163,350),'1:150' if phase==0 else '1:100',18,BLUE)
  if phase==2:
   d.arc((361,326,381,351),180,360,fill=GREEN,width=3)
   d.rectangle((358,339,384,360),fill=GREEN)
 elif idx==5:
  # Local magnification highlights movement; labels use the actual example.
  t=0 if phase==0 else progress if phase==1 else 1
  x=460+20*t
  for gy in range(180,411,30):line(d,[(80,gy),(580,gy)],GRID,1)
  for gx in range(80,581,30):line(d,[(gx,180),(gx,410)],GRID,1)
  line(d,[(100,330),(x,330),(x,190)],GREEN,4)
  d.ellipse((x-5,325,x+5,335),fill=BLUE)
  line(d,[(100,348),(100,382)],BLUE,1)
  line(d,[(x,348),(x,382)],BLUE,1)
  line(d,[(100,370),(x,370)],BLUE,2)
  text(d,(220,385),'3000 mm' if phase==2 else '2999.997 mm',24,WHITE)
  d.ellipse((x-25,305,x+25,355),outline=ORANGE,width=2)
  text(d,(110,201),'相连的两段墙线共同调整',18,MUTED)
  text(d,(110,233),'端点最大位移约 0.0036 mm',16,BLUE)
  text(d,(110,266),'局部位移放大示意',14,MUTED)
 elif idx==6:
  # Same scale in both directions: 2500 x 5000 bays and 6000 aisle.
  scale=.016;left=170;top=148;bw=2500*scale;bh=5000*scale;aisle=6000*scale
  d.rectangle((left-15,top-10,left+6*bw+15,top+2*bh+aisle+10),outline=BLUE,width=2)
  blocked={(0,2),(1,4)}
  for row,col in blocked:
   x=left+col*bw+14;y=top+row*(bh+aisle)+30
   d.rectangle((x,y,x+13,y+20),fill=MUTED)
  number=0
  for row in range(2):
   y=top+row*(bh+aisle)
   for col in range(6):
    x=left+col*bw
    bad=(row,col) in blocked
    if phase==0:continue
    if phase==1 and row*6+col>int(progress*12):continue
    if bad:
     if phase==1:
      d.rectangle((x,y,x+bw,y+bh),outline=ORANGE,width=2)
      line(d,[(x+8,y+12),(x+bw-8,y+bh-12)],ORANGE,2)
      line(d,[(x+bw-8,y+12),(x+8,y+bh-12)],ORANGE,2)
     continue
    number+=1
    # Open ends face the aisle; no end line blocks vehicle access.
    pts=[(x,y+bh),(x,y),(x+bw,y),(x+bw,y+bh)] if row==0 else [(x,y),(x,y+bh),(x+bw,y+bh),(x+bw,y)]
    line(d,pts,GREEN,2)
    if phase==2:text(d,(x+5,y+30),f'{number:02}',16,WHITE)
  cy=top+bh+aisle/2
  line(d,[(left+10,cy+17),(left+6*bw-10,cy+17)],BLUE,2)
  line(d,[(left+6*bw-20,cy+10),(left+6*bw-10,cy+17),(left+6*bw-20,cy+24)],BLUE,2)
  text(d,(left+50,cy-20),'通道 6000 mm',16,BLUE)
  text(d,(435,177),'灰色：柱',16,MUTED)
  text(d,(435,208),'橙色：冲突',16,ORANGE)
  text(d,(435,239),'绿色：采用',16,GREEN)
  text(d,(165,426),'先排除冲突位置，再编号',16,MUTED)
 elif idx==7:
  # Three doors in real wall openings; jambs and leaf hinges align.
  line(d,[(70,235),(590,235)],GREEN,2)
  line(d,[(70,243),(590,243)],GREEN,2)
  for j,(x,w) in enumerate([(115,36),(285,36),(455,48)]):
   d.rectangle((x,233,x+w,245),fill=BG)
   for xx in (x,x+w):line(d,[(xx,235),(xx,243)],GREEN,2)
   line(d,[(x,235),(x,235-w)],ORANGE,3)
   d.arc((x-w,235-w,x+w,235+w),270,360,fill=MUTED,width=1)
   text(d,(x-20,155),['900×2100','900×2100','1200×2100'][j],16,MUTED)
   if phase>=1:text(d,(x-2,253),['M01','M01','M02'][j],18,BLUE)
  for x in (170,395):
   for y in (299,304,309):line(d,[(x,y),(x+60,y)],BLUE,2)
   for xx in (x,x+60):line(d,[(xx,296),(xx,312)],GREEN,2)
   text(d,(x-17,321),'C01' if phase>=1 else '1500×1500',16,BLUE if phase>=1 else MUTED)
  if phase==0:text(d,(140,390),'属性：宽、高、材质、防火等级',18,MUTED)
  elif phase==1:text(d,(145,390),'相同规格 → 相同型号',20,GREEN)
  else:
   d.rectangle((95,361,590,441),outline=MUTED,width=1)
   for xx in (260,425):line(d,[(xx,361),(xx,441)],MUTED,1)
   for j,(label,count) in enumerate([('M01','2 樘'),('M02','1 樘'),('C01','2 樘')]):
    text(d,(120+j*165,370),label,18,BLUE);text(d,(120+j*165,405),count,18,GREEN)
 elif idx==8:
  if phase==0:
   for j,label in enumerate(['零长度与重复实体','门窗编号一致性','外参、字体、打印样式','检查读取范围是否完整']):
    y=165+j*60
    text(d,(125,y),label,18,WHITE)
    if j<=int(progress*4):
     line(d,[(80,y+12),(88,y+20),(104,y)],GREEN,3)
   text(d,(115,414),'本例各项检查通过',16,GREEN)
  else:
   # The original stays in place while two separate outputs are produced.
   d.rounded_rectangle((65,230,235,340),radius=10,outline=MUTED,width=2)
   text(d,(85,250),'项目原图',24);text(d,(89,296),'保留当前图纸',16,MUTED)
   line(d,[(245,285),(300,285),(300,215),(340,215)],BLUE,2)
   line(d,[(300,285),(300,355),(340,355)],BLUE,2)
   for y,ext,label in [(155,'DWG','项目副本'),(295,'PDF','指定布局')]:
    d.rounded_rectangle((350,y,575,y+115),radius=10,outline=GREEN if phase==2 else BLUE,width=2)
    text(d,(370,y+12),ext,24,BLUE);text(d,(370,y+52),label,18)
    if phase==2:text(d,(460,y+82),'已核验',16,GREEN)
   text(d,(160,431),'附带外部依赖清单',16,MUTED)
 text(d,(30,472),['确认对象与范围','按指令处理','查看结果，继续下一步'][phase],20)
 text(d,(30,508),'示例数据与图形仅用于说明操作流程',14,MUTED)
 d.rounded_rectangle((650,489,930,495),radius=3,fill=PANEL)
 d.rounded_rectangle((650,489,650+int(280*(frame+1)/36),495),radius=3,fill=BLUE)
 return im

for idx,scene in enumerate(SCENES):
 if args.only and scene[0] not in args.only:continue
 frames=[render(idx,i) for i in range(36)]
 durations=[110]*36
 for i in (11,23,35):durations[i]=1800
 frames[0].save(OUT/(scene[0]+'.gif'),save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True,disposal=2)
 print(scene[0],(OUT/(scene[0]+'.gif')).stat().st_size)
# One contact sheet lets maintainers inspect all three stages of every scene.
contact=Image.new('RGB',(960,180*len(SCENES)),BG)
for idx in range(len(SCENES)):
 for phase in range(3):contact.paste(render(idx,phase*12+11).resize((320,180)),(phase*320,idx*180))
contact.save(OUT/'demo-overview.png')
