import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
import sys
OUT = sys.argv[1]
BG="#0B0E13"; LN="#E8EBF0"; DIM="#7FD1FF"; PCB="#2BD67B"; HV="#FF4D6D"; GOLD="#FDC300"; VI="#C084FC"; GR="#8A94A6"
plt.rcParams.update({"font.family":"Consolas","font.size":11})
fig=plt.figure(figsize=(16,9),facecolor=BG); ax=fig.add_axes([0,0,1,1]); ax.set_facecolor(BG); ax.set_xlim(0,320); ax.set_ylim(0,180); ax.axis("off")
def dim(x1,y1,x2,y2,txt,off=6,vert=False):
    if not vert:
        ax.annotate("",(x1,y1-off),(x2,y2-off),arrowprops=dict(arrowstyle="<->",color=DIM,lw=1))
        ax.plot([x1,x1],[y1,y1-off-2],color=DIM,lw=.6); ax.plot([x2,x2],[y2,y2-off-2],color=DIM,lw=.6)
        ax.text((x1+x2)/2,y1-off-4.5,txt,color=DIM,ha="center",fontsize=12)
    else:
        ax.annotate("",(x1-off,y1),(x2-off,y2),arrowprops=dict(arrowstyle="<->",color=DIM,lw=1))
        ax.plot([x1,x1-off-2],[y1,y1],color=DIM,lw=.6); ax.plot([x2,x2-off-2],[y2,y2],color=DIM,lw=.6)
        ax.text(x1-off-3,(y1+y2)/2,txt,color=DIM,ha="right",va="center",fontsize=12,rotation=90)
X,Y,s=30,70,1.25
def R(x,y,w,h,ec,fc="none",lw=1.4,ls="-"): ax.add_patch(Rectangle((X+x*s,Y+y*s),w*s,h*s,ec=ec,fc=fc,lw=lw,ls=ls))
R(0,0,90,70,LN,lw=2); R(2.5,2.5,85,65,GR,lw=.8,ls="--"); R(5,5,80,60,PCB,fc="#0f2a1c",lw=1.6)
for hx,hy in [(9,9),(81,9),(9,61),(81,61)]:
    ax.add_patch(Circle((X+hx*s,Y+hy*s),1.75*s,ec=HV,fc="none",lw=1.2))
R(73.5,36,1.2,29,HV,fc=HV,lw=.5); R(74.7,36,9.3,28,HV,lw=1,ls="--")
ax.text(X+79.3*s,Y+59*s,"HV",color=HV,ha="center",fontsize=10,fontweight="bold"); ax.text(X+79.3*s,Y+40*s,"J5\nAC tap\n\nJ6\nCT",color=HV,ha="center",fontsize=8)
# name, x, y, w, h, colour, label dx, label dy (mm, relative to box centre-top)
comp=[("C1 ESP32-S3-WROOM-1",8,32,18,25.5,GOLD,0,1),("C6 ATM90E32AS",37,33,10,10,LN,0,1),("C5 AMC1311",64,45,8,6,LN,-2,1),
("C3 INA228",42,21,5,5,LN,0,1),("C13 DAC",31,27,4,4,LN,0,1),("C7 ULN2003",51,15,11,4.5,LN,0,1),("C8 supervisor",62,24,5,4.5,LN,4,-9),
("C10 DS3231",30,11,10,7.5,LN,0,-11.5),("C11 ATECC608",45,5,5,4.5,LN,9,-3.5),("C12 PC817",64,35,8,5,LN,-7,-2.5),("C2 MP2315",3,18,8,8,LN,0,1)]
for n,x,y,w,h,c,dx,dy in comp:
    R(5+x,5+y,w,h,c,lw=1.3)
    ax.text(X+(5+x+w/2+dx)*s,Y+(5+y+h+dy)*s,n,color=c,ha="center",fontsize=8.5)
ax.add_patch(Circle((X+22*s,Y+17*s),8.5*s,ec=LN,fc="none",lw=1)); ax.text(X+22*s,Y+17*s,"CR2032",color=GR,ha="center",va="center",fontsize=8)
for i,lab in enumerate(["J1 BAT+","J2 S+/S-","J3 BAT-","J4 NTC","J8 COIL×4","J9 AUX","J11 USB-C"]):
    R(7+i*11.3,1,10,5,VI,fc="#2a1a3a",lw=1); ax.text(X+(12+i*11.3)*s,Y-3.5,lab,color=VI,ha="center",fontsize=8)
dim(X,Y-9,X+90*s,Y-9,"90.0",off=4); dim(X-2,Y,X-2,Y+70*s,"70.0",off=4,vert=True)
ax.text(X+45*s,Y+70*s+5,"TOP VIEW  ·  lid removed",color=LN,ha="center",fontsize=14,fontweight="bold")
FX,FY=170,120
ax.add_patch(Rectangle((FX,FY),90*s,35*s,ec=LN,fc="none",lw=2)); ax.plot([FX,FX+90*s],[FY+32.5*s,FY+32.5*s],color=GR,lw=.8,ls="--"); ax.text(FX+88*s,FY+29.5*s,"lid 2.0",color=GR,ha="right",fontsize=8)
for i in range(7): ax.add_patch(Rectangle((FX+(7+i*11.3)*s,FY+4*s),10*s,6*s,ec=VI,fc="#2a1a3a",lw=1))
ax.add_patch(Rectangle((FX+3*s,FY+2*s),84*s,1.6*s,ec=PCB,fc=PCB,lw=.5)); ax.text(FX+45*s,FY+16*s,"terminal cut-outs J1–J11",color=VI,ha="center",fontsize=9)
dim(FX,FY-2,FX+90*s,FY-2,"90.0",off=3); dim(FX-2,FY,FX-2,FY+35*s,"35.0",off=3,vert=True)
ax.text(FX+45*s,FY+35*s+4,"FRONT VIEW",color=LN,ha="center",fontsize=14,fontweight="bold")
SX,SY=178,54
ax.add_patch(Rectangle((SX,SY),70*s,35*s,ec=LN,fc="none",lw=2)); ax.add_patch(Rectangle((SX-8,SY),8,6,ec=LN,fc="none",lw=1)); ax.text(SX-12,SY+8,"mount\ntab",color=GR,ha="left",fontsize=8)
ax.add_patch(Rectangle((SX+5*s,SY+2*s+3),60*s,1.6*s,ec=PCB,fc=PCB)); ax.text(SX+35*s,SY+11*s,"PCB 1.6 on M3 stand-offs",color=PCB,ha="center",fontsize=9)
dim(SX,SY-2,SX+70*s,SY-2,"70.0",off=3)
ax.text(SX+35*s,SY+35*s+4,"SIDE VIEW",color=LN,ha="center",fontsize=14,fontweight="bold")
ax.add_patch(Rectangle((170,4),140,36,ec=LN,fc="none",lw=1.4))
ax.text(174,34.5,"V-GUARD SENTINEL CORE — ENCLOSURE & PCB",color=GOLD,fontsize=13,fontweight="bold")
notes=["Enclosure 90 × 70 × 35 mm · PC/ABS UL94 V-0 · wall 2.5 · IP20","PCB 80 × 60 × 1.6 · 4× M3 (Ø3.5) at 4 mm inset","Battery current never enters the PCB — only shunt mV (J2)","AMC1311 + PC817 straddle the HV isolation moat","Coil off = load on: ULN2003 + supervisory timer + JP1","Units mm · per prototype/02–03 (round 3) · Rev T1"]
for i,n in enumerate(notes): ax.text(174,28.5-i*4.3,n,color=LN,fontsize=10)
fig.savefig(OUT,dpi=150,facecolor=BG)
