import * as engine from '@cesium/engine';
import {createWorldScene} from './scene.js';
export function createScene(options){return createWorldScene({...options,engine});}
