const test=require('node:test');
const assert=require('node:assert/strict');
const {validWeek,paintRange,ranges,clock}=require('../app/static/work_schedule.js');
const blank=()=>Array.from({length:7},()=>Array(48).fill(false));
test('half-open ranges preserve every other weekday and do not mutate input',()=>{
 const original=blank(),edited=paintRange(original,0,12,44,true);
 assert.equal(edited[0].filter(Boolean).length,32);
 assert.equal(edited[0][11],false);assert.equal(edited[0][44],false);
 assert.deepEqual(edited.slice(1),original.slice(1));assert.deepEqual(original,blank());
 assert.equal(ranges(edited[0]),'06:00–22:00');
});
test('midnight ends at 24:00 without enabling the next day',()=>{
 const week=paintRange(blank(),6,47,48,true);
 assert.equal(ranges(week[6]),'23:30–24:00');assert.deepEqual(week[0],blank()[0]);
 assert.equal(clock(48),'24:00');
});
test('on/off painting supports split periods and full days',()=>{
 const full=paintRange(blank(),3,0,48,true);
 assert.equal(ranges(full[3]),'00:00–24:00');
 assert.equal(ranges(paintRange(full,3,16,32,false)[3]),'00:00–08:00, 16:00–24:00');
});
test('bad day/interval/value and malformed plans cannot produce edits',()=>{
 for(const args of [[-1,0,1,true],[7,0,1,true],[0,2,1,true],[0,0,49,true],[0,0,.5,true],[0,0,1,1]])assert.throws(()=>paintRange(blank(),...args));
 const invalid=blank();invalid[0][0]=1;assert.equal(validWeek(invalid),false);
 assert.throws(()=>paintRange(invalid,0,0,1,true));
});
