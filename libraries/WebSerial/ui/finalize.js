// Finalize Nodejs Script
// 1 - Append JS in HTML Document
// 2 - Gzip HTML
// 3 - Covert to Raw Bytes
// 4 - ( Save to File: webpage.h ) in dist Folder

const fs = require('fs');
const zlib = require('zlib');
const { gzip } = require('@gfx/zopfli');

function getByteArray(file){
    let fileData = file.toString('hex');
    let result = [];
    for (let i = 0; i < fileData.length; i+=2)
      result.push('0x'+fileData[i]+''+fileData[i+1]);
    return result;
}

let js = fs.readFileSync(__dirname+'/dist/js/app.js');
let html = `
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>WebSerial</title>
    <script data-name="BMC-Widget" async src="https://cdnjs.buymeacoffee.com/1.0.0/widget.prod.min.js" data-id="6QGVpSj" data-description="Support me on Buy me a coffee!" data-message="You can always support my work by buying me a coffee!" data-color="#FF813F" data-position="right" data-x_margin="24" data-y_margin="24"></script>
  </head>
  <body>
    <noscript>
      <strong>We're sorry but WebSerial doesn't work properly without JavaScript enabled. Please enable it to continue.</strong>
    </noscript>
    <div id="app"></div>
    <script>${js}</script>
  </body>
</html>

`;
// Gzip the index.html file with JS Code.
const gzippedIndex = zlib.gzipSync(html, {'level': zlib.constants.Z_BEST_COMPRESSION});
let indexHTML = getByteArray(gzippedIndex);

let source = 
`
const uint32_t WEBSERIAL_HTML_SIZE = ${indexHTML.length};
const uint8_t WEBSERIAL_HTML[] PROGMEM = { ${indexHTML} };
`;


fs.writeFileSync(__dirname+'/dist/webpage.h', source, 'utf8');

// Produce a second variant with zopfli
// Zopfli is a improved zip algorithm by google
// Takes much more time and maybe is not available on every machine
const input =  html;
gzip(input, {numiterations: 15}, (err, output) => {
    indexHTML = output;
    let source =
`
const uint32_t WEBSERIAL_HTML_SIZE = ${indexHTML.length};
const uint8_t WEBSERIAL_HTML[] PROGMEM = { ${indexHTML} };
`;

  fs.writeFileSync(__dirname + '/dist/webpage_zopfli.h', source, 'utf8');
});
