import {defineConfig} from 'vite';
export default defineConfig({build:{target:'es2022',lib:{entry:'src/index.js',name:'KnightWorldBundle',formats:['iife'],fileName:()=> 'world.js'},rollupOptions:{output:{inlineDynamicImports:true}},sourcemap:false}});
