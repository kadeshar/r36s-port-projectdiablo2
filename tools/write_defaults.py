"""Create non-personal initial templates. Never overwrite active settings or data."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
PORT=ROOT/'sdcard/ports/projectdiablo2';D=PORT/'defaults'
def put(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if path.read_text(encoding='utf-8')!=text:raise RuntimeError('Existing template differs: '+path.name)
 else:path.write_text(text,encoding='utf-8',newline='\n')
def js(name,data):put(D/name,json.dumps(data,indent=2)+'\n')
js('ProjectDiablo.json',{
 'classic_game_settings':{
 'audio':{'sound_mixer':0,'master_volume':50,'music_volume':30,'positional_bias':0,'npc_speech':2,'options_music':1,'options_music_volume':30,'ui_volume':100,'items_volume':100,'monsters_volume':100,'skills_volume':100,'combat_volume':100,'ambient_volume':100,'voice_volume':100,'quest_volume':100,'objects_volume':100,'item_drop_volume':60},
 'video':{'contrast':75,'gamma':100,'perspective':0,'light_quality':0,'blended_shadows':0},
 'map':{'automapfade':3,'automap_centers':1,'automap_party':1,'automap_party_names':1,'automap_left':1,'automapmode':0},
 'ui':{'show_hp_text':1,'show_mp_text':1,'help_menu':0,'popuphireling':1,'always_run':1,'mini_panel':0},
 'bnet':{'skip_to_open':0,'aux_battle_net':'','lasttcpip':'','preferred_realm':'','default_channel':'','last_bnet':'','max_player':8,'diff_level':0,'lvl_rest':666,'selected_game_server':0,'loot_alloc':0},
 'other':{'lng_file':'','installpath':'C:\\Diablo II\\','save_path':'S:\\'}},
 'pd2_game_settings':{'equipment_lock':False,'buff_timers':True,'quick_cast':False,'skill_bar':True,'screenshake':False,'dps':False,'belt_status':True,'translucent_party':False,'wasd_movement':True,'controller_movement':False,'controller_sensitivity':50,'controller_aim_assist':1,'controller_deadzone':20,'auto_equip':True,'always_regenerate_levels':False,'player_count':1,'auras':{'dev_aura':0,'max_level_aura':0,'rathma_aura':0,'dclone_aura':0,'pvp_aura':0,'lucion_aura':0},'showItemHelpText':True,'controller_button_style':0,'controllerMultiButtonLoot':False,'autosync':False,'elme_potter':False}})
js('SGD2FreeResolution.json',{'SlashGaming Diablo II Free Resolution':{'!!!Metadata (Do not modify)!!!':{'Major Version A':3,'Major Version B':0,'Minor Version A':1,'Minor Version B':0},'Ingame Resolutions':['1024x768','800x600'],'Ingame Resolution Mode':1,'Main Menu Resolution':'1024x768','Custom MPQ File':'SGD2FreeRes.mpq','Enable Screen Border Frame?':False,'Use Original Screen Border Frame?':False,'Use 800 Interface Bar?':True},'!!!Globals!!!':{'Config Tab Width':4}})
js('BH.json',{'bnet':{'autofill_last_game':False,'autofill_next_game':False,'autofill_last_password':False,'autofill_description':False,'save_last_game':'','save_last_pass':'','save_last_desc':''},'general':{'stats_on_right':False},'lootfilter':{'filter_level':0,'advanced_item_display':False,'show_iLvl':False,'detailed_notifications':0,'drop_sounds':True},'game':{'experience_meter':False,'always_show_items':False},'party':{'auto_party':{'enabled':False,'hotkey':'None'},'auto_corpse_loot':{'enabled':False,'hotkey':'None'}},'screen_info':{'automap_info':['%LEVEL%','%GAMEDIFF%'],'hide_game_password':True},'stash_export':{'export_on_menu':{'enabled':False,'hotkey':'None'}},'bh_ui':{'is_minimized':True,'opened_x':20,'opened_y':20,'minimized_x':20,'minimized_y':400,'size_x':400,'size_y':300}})
put(D/'ProjectDiablo.cfg','// Offline handheld defaults; active user configuration is separate.\nAutofill Last Game: False\nAutofill Next Game: False\nAutofill Last Password: False\nAutofill Description: False\nAdvanced Item Display: False, None\nParty Enabled: False, None\nLooting Enabled: False, None\n')
put(D/'default.filter',"// Default filter (don't filter anything!)\n")
for renderer in ['gdi','opengl']:
 put(D/('ddraw-'+renderer+'.ini'),f'''[ddraw]
width=1024
height=768
fullscreen=false
windowed=true
maintas=false
boxing=false
maxfps=30
vsync=false
adjmouse=false
shader=
posX=0
posY=0
renderer={renderer}
devmode=false
border=false
savesettings=0
resizeable=false
vhack=false
maxgameticks=-1
handlemouse=true
hook=4
minfps=0
nonexclusive=true
singlecpu=false
''')
controls='''# SDL logical buttons; firmware A/B swap is handled by PortMaster mapping.
back = "
start = enter
guide = "
a = mouse_left
b = mouse_right
x = i
y = tab
l1 = f1
r1 = f2
l2 = leftshift
r2 = mouse_slow
l3 = "
r3 = "
up = 1
right = 2
down = 3
left = 4
left_analog_up = w
left_analog_down = s
left_analog_left = a
left_analog_right = d
right_analog_up = mouse_movement_up
right_analog_down = mouse_movement_down
right_analog_left = mouse_movement_left
right_analog_right = mouse_movement_right
a_hk = leftalt
b_hk = esc
x_hk = c
y_hk = s
l1_hk = f3
r1_hk = f4
l2_hk = t
r2_hk = r
deadzone_mode = scaled_radial
deadzone = 5000
deadzone_scale = 8
mouse_delay = 16
mouse_scale = 8192
mouse_slow_scale = 35
'''
put(D/'controls.gptk',controls)
put(D/'controls-swap.gptk',controls.replace('a = mouse_left\nb = mouse_right','a = mouse_right\nb = mouse_left').replace('a_hk = leftalt\nb_hk = esc','a_hk = esc\nb_hk = leftalt'))
put(PORT/'port.json',json.dumps({'version':2,'name':'projectdiablo2.zip','items':['Project Diablo 2.sh','projectdiablo2/'],'items_opt':None,'attr':{'title':'Project Diablo 2 (experimental offline)','desc':'Private experimental Wine/Box86 wrapper for R36S dArkOSen; not a native or approved PortMaster port.','inst':'Requires your legal English Diablo II + LoD and PD2 data. See README. Hardware testing required.','genres':['rpg','action'],'porter':['Private local experiment'],'image':{},'rtr':False,'runtime':None,'reqs':[],'arch':['aarch64']}},indent=2)+'\n')
put(PORT/'gameinfo.xml','<?xml version="1.0" encoding="UTF-8"?>\n<gameList><game><path>./Project Diablo 2.sh</path><name>Project Diablo 2 - offline (experimental)</name><desc>Wine/Box86, dArkOSen R36S. Hardware test required.</desc><genre>RPG</genre></game></gameList>\n')
print('Initial templates created; no user settings or game data touched.')
