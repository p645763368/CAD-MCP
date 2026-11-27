"""Generate README workflow illustrations. Requires Pillow and a Chinese font.
Usage: python scripts/render_readme_demos.py --font C:/Windows/Fonts/msyh.ttc
Synthetic diagrams only; never connects to AutoCAD or opens project drawings.
"""
from pathlib import Path
import argparse, math
from PIL import Image, ImageDraw, ImageFont
parser=argparse.ArgumentParser()
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
 ('viewport-scale','检查布局',['选定普通视口','设置 1:100','锁定并核对'],['布局视口设置','对象：指定普通视口','原比例：1:150','目标比例：1:100','视口状态：已锁定','其他视口：保留原设置'])]

def text(d,xy,s,size=18,color=WHITE): d.text(xy,s,font=FONT[size],fill=color)
def line(d,points,color=GREEN,width=3):d.line(points,fill=color,width=width)
def roomplan(d):
 for x in range(40,630,25):line(d,[(x,135),(x,430)],GRID,1)
 for y in range(135,440,25):line(d,[(40,y),(620,y)],GRID,1)
 d.rectangle((100,175,550,390),outline=GREEN,width=4)
 line(d,[(100,282),(550,282)])
 line(d,[(250,175),(250,282)])
 line(d,[(400,175),(400,282)])
 line(d,[(325,282),(325,390)])
 for x in (180,330,480):
  line(d,[(x-15,282),(x+15,282)],BG,6)
  line(d,[(x,267),(x,297)],ORANGE,4)

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
    line(d,[(x,267),(x,297)],col,5)
    if phase==0:
     d.rectangle((x-22,254,x+22,310),outline=BLUE,width=2)
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
 text(d,(30,472),['确认对象与范围','按指令处理','查看结果，继续下一步'][phase],20)
 text(d,(30,508),'示例数据与图形仅用于说明操作流程',14,MUTED)
 d.rounded_rectangle((650,489,930,495),radius=3,fill=PANEL)
 d.rounded_rectangle((650,489,650+int(280*(frame+1)/36),495),radius=3,fill=BLUE)
 return im

for idx,scene in enumerate(SCENES):
 frames=[render(idx,i) for i in range(36)]
 durations=[110]*36
 for i in (11,23,35):durations[i]=1800
 frames[0].save(OUT/(scene[0]+'.gif'),save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True,disposal=2)
 print(scene[0],(OUT/(scene[0]+'.gif')).stat().st_size)
# One contact sheet lets maintainers inspect all three stages of every scene.
contact=Image.new('RGB',(960,900),BG)
for idx in range(5):
 for phase in range(3):contact.paste(render(idx,phase*12+11).resize((320,180)),(phase*320,idx*180))
contact.save(OUT/'demo-overview.png')
