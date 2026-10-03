"""Create three short original notification WAVs with soft attacks and no external media."""
import math,struct,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'resources'/'audio'/'notifications'
RATE=44100

def render(name,duration,notes):
    samples=[]
    for i in range(round(duration*RATE)):
        t=i/RATE; value=0.0
        for start,length,frequency,gain,soft in notes:
            local=t-start
            if not 0<=local<length: continue
            attack=min(1,local/(.08 if soft else .012)); release=min(1,(length-local)/.07)
            envelope=math.sin(attack*math.pi/2)**2*math.sin(release*math.pi/2)**2*math.exp(-local*(2.0 if soft else 5.0))
            tone=math.sin(2*math.pi*frequency*local)+.10*math.sin(2*math.pi*frequency*2*local)
            value+=gain*tone*envelope
        samples.append(value)
    peak=max(abs(value) for value in samples); factor=.26/max(peak,1e-9)
    with wave.open(str(ROOT/name),'wb') as output:
        output.setparams((1,2,RATE,len(samples),'NONE','not compressed')); output.writeframes(b''.join(struct.pack('<h',round(value*factor*32767)) for value in samples))

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    render('gentle-bell.wav',.85,[(0,.55,523.25,.20,False),(.14,.55,659.25,.14,False),(.28,.55,783.99,.09,False)])
    render('clear-chime.wav',.72,[(0,.38,587.33,.16,False),(.18,.48,880.0,.10,False)])
    render('warm-chord.wav',.90,[(0,.88,261.63,.09,True),(0,.88,329.63,.07,True),(.07,.81,392.0,.06,True)])
    print('Created three mono PCM WAVs at 44.1 kHz; peak below -11 dBFS')

if __name__=='__main__': main()
