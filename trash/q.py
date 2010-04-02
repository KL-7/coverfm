from libs import pngcanvas

png1 = pngcanvas.PNGCanvas(128, 64)
png2 = pngcanvas.PNGCanvas(128, 128)
png1.load(open('test.png', 'rb'))
png1.copyRect(0, 0, 127, 63, 0, 0, png2)
png1.copyRect(0, 0, 127, 63, 0, 64, png2)
open('res.png', 'wb').write(png2.dump())
