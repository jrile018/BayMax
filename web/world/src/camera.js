export function fitDistance(radius,vfov,aspect,insetFraction=0){
 if(![radius,vfov,aspect,insetFraction].every(Number.isFinite)||radius<0||vfov<=0||vfov>=Math.PI||aspect<=0||insetFraction<0||insetFraction>=1)throw Error('invalid framing');
 const hfov=2*Math.atan(Math.tan(vfov/2)*aspect);
 return Math.max(150,radius/Math.sin(Math.min(vfov,hfov)/2)/(1-insetFraction));
}
export function validPick(value){
 if(!value||![value.longitude,value.latitude].every(Number.isFinite)||Math.abs(value.longitude)>Math.PI||Math.abs(value.latitude)>Math.PI/2)return null;
 return [value.longitude*180/Math.PI,value.latitude*180/Math.PI];
}
