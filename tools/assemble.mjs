// CLI and browser use exactly the same source-pitch and assembly code.
import { assemble } from '../web/rebuild.js';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
process.stdout.write(JSON.stringify(assemble(data.struct, data.geometry, data.chords || {})));
