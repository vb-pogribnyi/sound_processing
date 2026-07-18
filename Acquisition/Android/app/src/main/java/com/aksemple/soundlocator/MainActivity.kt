package com.aksemple.soundlocator

import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import androidx.compose.ui.graphics.Color
import android.hardware.usb.UsbManager
import android.opengl.GLES32
import android.opengl.GLSurfaceView
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.input.pointer.PointerType
import androidx.compose.ui.input.pointer.changedToUp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import com.aksemple.soundlocator.App.Companion.context
import com.aksemple.soundlocator.Communication.Companion.sendMotorSpeed
import com.aksemple.soundlocator.ui.theme.SoundLocatorTheme
import kotlinx.coroutines.sync.withLock
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.util.Collections.max
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.random.Random


//val heights = FloatArray(4096)
//var fft = FFT(4096)
class App : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    companion object {
        private lateinit var instance: App
        val context: Context get() = instance.applicationContext
    }
}

class MyGLRenderer : GLSurfaceView.Renderer {
    private var vbo = 0
    private var hvbo = 0
    private var ffta = 0
    private var fftb = 0

    private var uBarWidth = 0
    private var uBarCount = 0
    private var uFFTStage = 0
    private var uFFTSize = 0

    private val vertexData = floatArrayOf(
        -0.5f, 0f,
         0.5f, 0f,
        -0.5f, 1f,
         0.5f, 0f,
         0.5f, 1f,
        -0.5f, 1f
    )
    private val barCount = 4096
    private lateinit var vertexBuffer: FloatBuffer
    private var program: Int = 0
    private var compProgram: Int = 0
    private var compPreProgram: Int = 0
    private var compPostProgram: Int = 0

    val buffer = ByteBuffer
        .allocateDirect(barCount * 4)
        .order(ByteOrder.nativeOrder())
        .asFloatBuffer()

    fun loadShader(path: String): String {
        return context.assets.open(path).bufferedReader().use{
            it.readText()
        }
    }

    fun compileShader(type: Int, code: String): Int {
        val shader = GLES32.glCreateShader(type)
        GLES32.glShaderSource(shader, code)
        GLES32.glCompileShader(shader)
        val compileStatus = IntArray(1)
        GLES32.glGetShaderiv(shader, GLES32.GL_COMPILE_STATUS, compileStatus, 0)
        if (compileStatus[0] == 0) {
            val error = GLES32.glGetShaderInfoLog(shader)
            GLES32.glDeleteShader(shader)
            return 0
        }

        return shader
    }

    fun downloadBuffer(buffer: Int, size: Int): FloatArray {
        GLES32.glBindBuffer(GLES32.GL_SHADER_STORAGE_BUFFER, buffer)
        val mapped = GLES32.glMapBufferRange(GLES32.GL_SHADER_STORAGE_BUFFER,
            0, size * 4,
            GLES32.GL_MAP_READ_BIT) as ByteBuffer?
        mapped?.order(ByteOrder.nativeOrder())
        val floatBuffer = mapped?.asFloatBuffer()
        val result = FloatArray(size)
        floatBuffer?.get(result)
        GLES32.glUnmapBuffer(GLES32.GL_SHADER_STORAGE_BUFFER)

        return result
    }

    override fun onDrawFrame(p0: GL10?) {
        GLES32.glClear(GLES32.GL_COLOR_BUFFER_BIT)
        GLES32.glBindBuffer(GLES32.GL_SHADER_STORAGE_BUFFER, hvbo)
        buffer.put(Communication.fftBuffer)
        buffer.position(0)
        GLES32.glBufferSubData(
            GLES32.GL_SHADER_STORAGE_BUFFER,
            0,
            barCount * 4,
            buffer
        )

//        val N = barCount
//        val re = DoubleArray(N)
//        val im = DoubleArray(N)
//        for (i in 0..N - 1) {
//            re[i] = heights[i].toDouble()
//            im[i] = 0.0;
//        }
//        var correctFFT = fft.fft(re, im)
//
//        var hvboCPU = downloadBuffer(hvbo, barCount)
//        var fftaCPU = downloadBuffer(ffta, barCount*2)
//        var fftbCPU = downloadBuffer(fftb, barCount*2)

        // Compute
        GLES32.glUseProgram(compPreProgram)
        GLES32.glBindBufferBase(
            GLES32.GL_SHADER_STORAGE_BUFFER, 0, hvbo)
        GLES32.glBindBufferBase(
            GLES32.GL_SHADER_STORAGE_BUFFER, 1, ffta)
        GLES32.glDispatchCompute(barCount / 256, 1, 1)
        GLES32.glMemoryBarrier(GLES32.GL_SHADER_STORAGE_BARRIER_BIT)
//        hvboCPU = downloadBuffer(hvbo, barCount)
//        fftaCPU = downloadBuffer(ffta, barCount*2)
//        fftbCPU = downloadBuffer(fftb, barCount*2)

        GLES32.glUseProgram(compProgram)
        for (stage in 0 until 12) {
            GLES32.glUniform1i(uFFTSize, barCount)
            GLES32.glUniform1i(uFFTStage, stage)
            GLES32.glBindBufferBase(
                GLES32.GL_SHADER_STORAGE_BUFFER, 0,
                if (stage % 2 == 0) ffta else fftb
            )
            GLES32.glBindBufferBase(GLES32.GL_SHADER_STORAGE_BUFFER, 1,
                if (stage % 2 == 0) fftb else ffta)
            GLES32.glDispatchCompute(barCount / 256, 1, 1)
            GLES32.glMemoryBarrier(GLES32.GL_SHADER_STORAGE_BARRIER_BIT)


//            // Read back for inspection
//            hvboCPU = downloadBuffer(hvbo, barCount)
//            fftaCPU = downloadBuffer(ffta, barCount*2)
//            fftbCPU = downloadBuffer(fftb, barCount*2)
        }
        GLES32.glUseProgram(compPostProgram)
        GLES32.glBindBufferBase(
            GLES32.GL_SHADER_STORAGE_BUFFER, 0, ffta)
        GLES32.glBindBufferBase(
            GLES32.GL_SHADER_STORAGE_BUFFER, 1, hvbo)
        GLES32.glDispatchCompute(barCount / 256, 1, 1)
        GLES32.glMemoryBarrier(GLES32.GL_SHADER_STORAGE_BARRIER_BIT)

//        hvboCPU = downloadBuffer(hvbo, barCount)
//        fftaCPU = downloadBuffer(ffta, barCount*2)
//        fftbCPU = downloadBuffer(fftb, barCount*2)

        // Draw
        var binsCount = 512
        GLES32.glUseProgram(program)
        GLES32.glUniform1f(uBarWidth, 0.004f)
        GLES32.glUniform1f(uBarCount, binsCount.toFloat())
        GLES32.glBindVertexArray(vbo)
        GLES32.glDrawArraysInstanced(GLES32.GL_TRIANGLES, 0, 6, binsCount)
        GLES32.glBindVertexArray(0)
    }

    override fun onSurfaceChanged(
        p0: GL10?,
        p1: Int,
        p2: Int
    ) {
        GLES32.glViewport(0, 0, p1, p2)
    }

    override fun onSurfaceCreated(
        p0: GL10?,
        p1: EGLConfig?
    ) {
//        for (i in 0..barCount-1) {
//            heights[i] = sin(i.toFloat() / barCount * 50 * 3.1415f)
//            heights[i] += sin(i.toFloat() / barCount * 12 * 3.1415f)
//            heights[i] += sin(i.toFloat() / barCount * 250 * 3.1415f)
//        }
//        heights[1024] = 1.0f
        GLES32.glClearColor(1f, 1f, 1f, 1f  )
//        GLES32.glEnable(GLES32.GL_BLEND)
//        GLES32.glBlendFunc(GLES32.GL_SRC_ALPHA, GLES32.GL_ONE_MINUS_SRC_ALPHA)
        val vert = compileShader(GLES32.GL_VERTEX_SHADER, loadShader("fft.vert"))
        val frag = compileShader(GLES32.GL_FRAGMENT_SHADER, loadShader("fft.frag"))
        val comp = compileShader(GLES32.GL_COMPUTE_SHADER, loadShader("fft.comp"))
        val comp_pre = compileShader(GLES32.GL_COMPUTE_SHADER, loadShader("fft_pre.comp"))
        val comp_post = compileShader(GLES32.GL_COMPUTE_SHADER, loadShader("fft_post.comp"))

        program = GLES32.glCreateProgram()
        compProgram = GLES32.glCreateProgram()
        compPreProgram = GLES32.glCreateProgram()
        compPostProgram = GLES32.glCreateProgram()
        GLES32.glAttachShader(program, vert)
        GLES32.glAttachShader(program, frag)
        GLES32.glAttachShader(compProgram, comp)
        GLES32.glAttachShader(compPreProgram, comp_pre)
        GLES32.glAttachShader(compPostProgram, comp_post)
        GLES32.glLinkProgram(program)
        val linkStatus = IntArray(1)
        GLES32.glGetProgramiv(program, GLES32.GL_LINK_STATUS, linkStatus, 0)
        if (linkStatus[0] == 0) {
            val error = GLES32.glGetProgramInfoLog(program)
            GLES32.glDeleteProgram(program)
            return
        }
        GLES32.glLinkProgram(compProgram)
        GLES32.glGetProgramiv(compProgram, GLES32.GL_LINK_STATUS, linkStatus, 0)
        if (linkStatus[0] == 0) {
            val error = GLES32.glGetProgramInfoLog(compProgram)
            GLES32.glDeleteProgram(compProgram)
            return
        }

        GLES32.glLinkProgram(compPreProgram)
        GLES32.glGetProgramiv(compPreProgram, GLES32.GL_LINK_STATUS, linkStatus, 0)
        if (linkStatus[0] == 0) {
            val error = GLES32.glGetProgramInfoLog(compPreProgram)
            GLES32.glDeleteProgram(compPreProgram)
            return
        }

        GLES32.glLinkProgram(compPostProgram)
        GLES32.glGetProgramiv(compPostProgram, GLES32.GL_LINK_STATUS, linkStatus, 0)
        if (linkStatus[0] == 0) {
            val error = GLES32.glGetProgramInfoLog(compPostProgram)
            GLES32.glDeleteProgram(compPostProgram)
            return
        }

        vertexBuffer = ByteBuffer
            .allocateDirect(vertexData.size * 4)
            .order(ByteOrder.nativeOrder())
            .asFloatBuffer()
            .put(vertexData)
        vertexBuffer.position(0)

        val buffers = IntArray(1)
        GLES32.glGenBuffers(1, buffers, 0)
        vbo = buffers[0]
        GLES32.glBindBuffer(GLES32.GL_ARRAY_BUFFER, vbo)
        GLES32.glBufferData(
            GLES32.GL_ARRAY_BUFFER,
            vertexData.size * 4,
            vertexBuffer,
            GLES32.GL_STATIC_DRAW
        )
//        GLES32.glBindBuffer(GLES32.GL_ARRAY_BUFFER, vbo)
        GLES32.glEnableVertexAttribArray(0)
        GLES32.glVertexAttribPointer(
            0, 2,
            GLES32.GL_FLOAT,
            false,
            2 * 4, 0
        )
        GLES32.glBindVertexArray(0)


        GLES32.glGenBuffers(1, buffers, 0)
        hvbo = buffers[0]
//        GLES32.glBindBuffer(GLES32.GL_SHADER_STORAGE_BUFFER, hvbo)
        GLES32.glBindBuffer(GLES32.GL_ARRAY_BUFFER, hvbo)
        GLES32.glBufferData(
//            GLES32.GL_SHADER_STORAGE_BUFFER,
            GLES32.GL_ARRAY_BUFFER,
            barCount * 4,
            null,
            GLES32.GL_DYNAMIC_DRAW
        )
        GLES32.glEnableVertexAttribArray(1)
        GLES32.glVertexAttribPointer(
            1, 1,
            GLES32.GL_FLOAT,
            false,
            0, 0
        )
        GLES32.glVertexAttribDivisor(1, 1)
//        GLES32.glBindBufferBase(
//            GLES32.GL_SHADER_STORAGE_BUFFER, 0, ssbo
//        )


        GLES32.glGenBuffers(1, buffers, 0)
        ffta = buffers[0]
        GLES32.glGenBuffers(1, buffers, 0)
        fftb = buffers[0]
        GLES32.glBindBuffer(GLES32.GL_SHADER_STORAGE_BUFFER, ffta)
        GLES32.glBufferData(
            GLES32.GL_SHADER_STORAGE_BUFFER,
            barCount * 8, // Complex values, 8 bytes per value
            null,
            GLES32.GL_DYNAMIC_DRAW
        )
        GLES32.glBindBuffer(GLES32.GL_SHADER_STORAGE_BUFFER, fftb)
        GLES32.glBufferData(
            GLES32.GL_SHADER_STORAGE_BUFFER,
            barCount * 8, // Complex values, 8 bytes per value
            null,
            GLES32.GL_DYNAMIC_DRAW
        )

        uBarWidth = GLES32.glGetUniformLocation(program, "uBarWidth")
        uBarCount = GLES32.glGetUniformLocation(program, "uBarCount")
        uFFTStage = GLES32.glGetUniformLocation(compProgram, "uStage")
        uFFTSize = GLES32.glGetUniformLocation(compProgram, "uSize")
    }

}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        Communication.usbManager = getSystemService(Context.USB_SERVICE) as UsbManager
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SoundLocatorTheme {
                Column {
                    Spacer(Modifier.padding(20.dp))
                    Greeting()
                }
            }
        }
    }
}


@Composable
fun Greeting(modifier: Modifier = Modifier) {
    val activity = LocalActivity.current
    var status by Communication.status
    var interruptStatus by Communication.interruptStatus
    var interruptData by Communication.interruptData
    var anotherStatus by Communication.anotherStatus
    var bulkReadsSuccess by Communication.bulkReadsSuccess
    var bulkReadsFail by Communication.bulkReadsFail
    val context = LocalContext.current
    val canvasColor = Color.LightGray
    val canvasLineWidth = 3.0f
    var pointerPos by remember { mutableStateOf<Offset?>(null) }
    var isDropShown by remember { mutableStateOf(false) }
    var motor1Val by Communication.motor1Val
    var motor2Val by Communication.motor2Val
    var micsAngle by Communication.micsAngle
    var fftVis by Communication.fftVis


    var isTraceRequested by Communication.isTraceRequested
    var isPeriodicRequested by Communication.isPeriodicRequested
    var bulkTime by Communication.bulkTime
    var rdyTime by Communication.rdyTime
    var rqstTime by Communication.rqstTime
    var traceBytes by Communication.traceBytes
    var periodicBytes by Communication.periodicBytes
    var mainReportedBytes by Communication.mainReportedBytes
    var mainReceivedBytes by Communication.mainReceivedBytes
    var epMain by Communication.epMain
    var epTrace by Communication.epTrace
    var epPer by Communication.epPer



    var text by remember { Communication.note }

    activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
    val spaceWidth = 5.dp
    val debugRowHeight = 20.dp
    Row(modifier=Modifier.fillMaxSize()) {
        Box(modifier = Modifier.weight(0.7f).fillMaxHeight()) {
            Column() {
                Row() {
                    Button(onClick = {
                        Communication.toggleLED()
                    }, modifier = Modifier.weight(0.9f), shape= RoundedCornerShape(5.dp)) { Text("LED") }
                    Spacer(Modifier.width(spaceWidth))
                    if (isTraceRequested > 0) {
                        Button(onClick = {
                            isTraceRequested = 1 - isTraceRequested
                        }, modifier = Modifier.weight(1.0f), shape= RoundedCornerShape(5.dp)) { Text("Trce") }
                    } else {
                        OutlinedButton(onClick = {
                            isTraceRequested = 1 - isTraceRequested
                        }, modifier = Modifier.weight(1.0f), shape= RoundedCornerShape(5.dp) ) { Text("Trce") }
                    }
                    Spacer(Modifier.width(spaceWidth))
                    if (isPeriodicRequested > 0) {
                        Button(onClick = {
                            isPeriodicRequested = 1 - isPeriodicRequested
                        }, modifier = Modifier.weight(1.0f), shape= RoundedCornerShape(5.dp)) { Text("Smpl") }
                    } else {
                        OutlinedButton(onClick = {
                            isPeriodicRequested = 1 - isPeriodicRequested
                        }, modifier = Modifier.weight(1.0f), shape= RoundedCornerShape(5.dp) ) { Text("Smpl") }
                    }
//                    Button(onClick = {
//                        Communication.toggleLED()
//
////                        for (i in 0..heights.size-1) {
////                            heights[i] += Random.nextFloat()*0.01f
////                        }
//                    }) { Text("LED") }
//                    Button(onClick = {
////                        if (Communication.pointerPosRel != null) {
////                            Communication.readBulk(pointerPosRel!!, context)
////                        }
//                        Communication.readBulk(context)
//                    }) { Text("Start") }
//                    Button(onClick = {
//                        val file = Communication.stopReadingBulk()
//                        val uri = FileProvider.getUriForFile(context, "${App.context.packageName}.fileprovider", file)
//                        val intent = Intent(Intent.ACTION_SEND).apply {
//                            type = "application/octet-stream"
//                            putExtra(Intent.EXTRA_STREAM, uri)
//                            setPackage("com.whatsapp")
//                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
//                        }
//                        try {
//                            context.startActivity(intent)
//                        } catch (e: Exception) {
//                            Toast.makeText(App.context, "Could not send...", Toast.LENGTH_SHORT).show()
//                        }
//                    }) { Text("Stop") }
                }
                Row() {
                    Button(onClick = {
                        Communication.readBulk()
                    }, modifier = Modifier.weight(1.0f)) { Text("Start") }
                    Spacer(Modifier.width(spaceWidth))
                    Button(onClick = {
                        Communication.stopReadingBulk()
                        if (isTraceRequested > 0 && Communication.seggerFile != null) {
                            val uri = FileProvider.getUriForFile(
                                context,
                                "${App.context.packageName}.fileprovider",
                                Communication.seggerFile!!
                            )
                            val intent = Intent(Intent.ACTION_SEND).apply {
                                type = "application/octet-stream"
                                putExtra(Intent.EXTRA_STREAM, uri)
                                setPackage("com.whatsapp")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            try {
                                context.startActivity(intent)
                            } catch (e: Exception) {
                                Toast.makeText(App.context, "Could not send...", Toast.LENGTH_SHORT)
                                    .show()
                            }
                        }
                        if (isPeriodicRequested > 0 && Communication.debugWav != null) {
                            val uri = FileProvider.getUriForFile(
                                context,
                                "${App.context.packageName}.fileprovider",
                                Communication.debugWav!!
                            )
                            val intent = Intent(Intent.ACTION_SEND).apply {
                                type = "application/octet-stream"
                                putExtra(Intent.EXTRA_STREAM, uri)
                                setPackage("com.whatsapp")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            try {
                                context.startActivity(intent)
                            } catch (e: Exception) {
                                Toast.makeText(App.context, "Could not send...", Toast.LENGTH_SHORT)
                                    .show()
                            }
                        }
                    }, modifier = Modifier.weight(1.0f)) { Text("Stop") }
                }
                Row() {
                    Button(onClick = {
                        context.startActivity(Intent(context, BrowseDatabaseActivity::class.java))
                    }, modifier = Modifier.weight(1.0f)) { Text("Browse Database") }
                }
                Row(Modifier.fillMaxSize()) {
                    // Timing/debug info goes here
                    Column {
                        Row(modifier = Modifier.fillMaxWidth().height(debugRowHeight)) {
                            val refTime = 100 // All timing displayed as percentage of 100 ms
                            Column(
                                modifier = Modifier.fillMaxHeight().weight(1.0f)
                            ) { Text("Timing %($refTime)") }
                            Spacer(Modifier.width(spaceWidth))
                            Column(
                                modifier = Modifier.fillMaxHeight().width(30.dp)
                            ) { Text(bulkTime.toInt().toString()) }
                            Spacer(Modifier.width(spaceWidth))
                            Column(
                                modifier = Modifier.fillMaxHeight().width(30.dp)
                            ) { Text(rdyTime.toInt().toString()) }
                            Spacer(Modifier.width(spaceWidth))
                            Column(
                                modifier = Modifier.fillMaxHeight().width(30.dp)
                            ) { Text(rqstTime.toInt().toString()) }
                        }
//                    Trace/periodic transer sizes
                        Row(modifier = Modifier.fillMaxWidth().height(debugRowHeight)) {
                            Column(
                                modifier = Modifier.fillMaxHeight().weight(1.0f)
                            ) { Text("Debug arrays") }
                            Spacer(Modifier.width(spaceWidth))
                            Column(modifier = Modifier.fillMaxHeight().width(45.dp)) {
                                Text(
                                    traceBytes.toString(),
                                    fontSize = 8.sp
                                )
                            }
                            Spacer(Modifier.width(spaceWidth*2))
                            Column(modifier = Modifier.fillMaxHeight().width(45.dp)) {
                                Text(
                                    periodicBytes.toString(),
                                    fontSize = 8.sp
                                )
                            }
//                            Spacer(Modifier.width(spaceWidth))
//                            Column(modifier = Modifier.fillMaxHeight().width(30.dp)) { Text("") }
                        }
//                    Trace/periodic transer sizes
                        Row(modifier = Modifier.fillMaxWidth().height(debugRowHeight)) {
                            Column(
                                modifier = Modifier.fillMaxHeight().weight(1.0f)
                            ) { Text("Main - reported/received") }
                            Spacer(Modifier.width(spaceWidth))
                            Column(modifier = Modifier.fillMaxHeight().width(45.dp)) {
                                Text(
                                    mainReportedBytes.toString(),
                                    fontSize = 8.sp
                                )
                            }
                            Spacer(Modifier.width(spaceWidth*2))
                            Column(modifier = Modifier.fillMaxHeight().width(45.dp)) {
                                Text(
                                    mainReceivedBytes.toString(),
                                    fontSize = 8.sp
                                )
                            }
//                            Spacer(Modifier.width(spaceWidth))
//                            Column(modifier = Modifier.fillMaxHeight().width(30.dp)) { Text("") }
                        }
//                    Endpoints numbers
                        Row(modifier = Modifier.fillMaxWidth().height(debugRowHeight)) {
                            Column(
                                modifier = Modifier.fillMaxHeight().weight(1.0f)
                            ) { Text("EP numbers") }
                            Spacer(Modifier.width(spaceWidth))
                            Column(modifier = Modifier.fillMaxHeight().width(30.dp)) {
                                Text(
                                    "M:" + epMain.toString()
                                )
                            }
                            Spacer(Modifier.width(spaceWidth))
                            Column(modifier = Modifier.fillMaxHeight().width(30.dp)) {
                                Text(
                                    "T:" + epTrace.toString()
                                )
                            }
                            Spacer(Modifier.width(spaceWidth))
                            Column(modifier = Modifier.fillMaxHeight().width(30.dp)) { Text(
                                "P:" + epPer.toString()
                            ) }
                        }
                    }
                }
//                Row() {
//                    Text(bulkReadsSuccess.toString(), color = Color.Green)
//                    Spacer(Modifier.width(25.dp))
//                    Text(bulkReadsFail.toString(), color = Color.Red)
//                }
//                Button(onClick = {
//                    Communication.startReadingInt()
//                }) { Text("Start reading Int") }
//                Text(interruptStatus)
//                Text(interruptData)
//                Button(onClick = {
//                    val file = Communication.stopReadingInt()
//
//                    val uri = FileProvider.getUriForFile(context, "${App.context.packageName}.fileprovider", file)
//                    val intent = Intent(Intent.ACTION_SEND).apply {
//                        type = "application/octet-stream"
//                        putExtra(Intent.EXTRA_STREAM, uri)
//                        setPackage("com.whatsapp")
//                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
//                    }
//                    try {
//                        context.startActivity(intent)
//                    } catch (e: Exception) {
//                        Toast.makeText(App.context, "Could not send...", Toast.LENGTH_SHORT).show()
//                    }
//                }) { Text("Stop reading Int") }
//                Row {
//                    for (status in Communication.statuses) {
//                        Text(status)
//                    }
//                }
//                Row {
//                    for (len in Communication.transferLengths) {
//                        Text(len)
//                    }
//                }
//                Text(anotherStatus)
//                Text(status)
            }
        }
        Box(modifier = Modifier.weight(0.45f).fillMaxHeight()) {
            Column(modifier = Modifier.fillMaxHeight()) {
                Row() {
                    Slider(
                        value = motor1Val,
                        onValueChange = { motor1Val = it },
                        onValueChangeFinished = { sendMotorSpeed(motor1Val, motor2Val) },
//                        modifier = Modifier
//                            .width(400.dp)
//                            .height(48.dp)
//                            .rotate(270f)
                    )
                }
                Row() {
                    Slider(
                        value = motor2Val,
                        onValueChange = { motor2Val = it },
                        onValueChangeFinished = { sendMotorSpeed(motor1Val, motor2Val) },
//                        modifier = Modifier
//                            .width(400.dp)
//                            .height(48.dp)
//                            .rotate(270f)
                    )
                }
                Row() {
                    Text(text = ((motor1Val * 100).toInt().toFloat() / 100).toString())
                }
                Row() {
                    Text(text = ((motor2Val * 100).toInt().toFloat() / 100).toString())
                }
                Row() {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { newText -> text = newText },
                        label = { Text("Note") },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                Row() {
                    Text(
                        fontSize = 50.sp,
                        text = micsAngle.toString()
                    )
                    Button(onClick = {
                        isDropShown = true
                    }) { Text("Select angle") }
                    DropdownMenu(
                        expanded = isDropShown,
                        onDismissRequest = { isDropShown = false }
                    ) {
                        for (i in -40..40 step 10) {
                            DropdownMenuItem(
                                text = {Text(i.toString())},
                                onClick = {
                                    micsAngle = i
                                    isDropShown = false
                                }
                            )
                        }
                    }
                }
                Row() {
                    Button(onClick = {
                        Communication.startExperiment()
                    }) { Text("Start") }
                    Button(onClick = {
                        Communication.stopExperiment()
                    }) { Text("Stop") }
                }
//                Row() {
//                    Button(onClick = {
//                        Communication.snapshot()
//                    }) { Text("Snapshot") }
//                }
            }
        }

//        Canvas(modifier = Modifier.weight(1f).fillMaxHeight().pointerInput(Unit) {
//            awaitEachGesture {
//                val event = awaitPointerEvent()
//                val stylusEvent = event.changes.find{it.type == PointerType.Stylus}
//                if (stylusEvent != null) {
//                    if (stylusEvent.pressed && !stylusEvent.previousPressed) {
//                        pointerPos = stylusEvent.position
//                    }
//                    if (pointerPos != null && !stylusEvent.pressed) {
//                        pointerPos = null
//                    }
//                }
//            }
//        }) {
//            drawPath(fftVis, Color(0x64000080))
////            Communication.isRenderDone.value = true
//            drawLine(
//                color = canvasColor,
//                Offset(0.0f, 0.0f),
//                Offset(size.width, 0.0f),
//                canvasLineWidth
//            )
//            drawLine(
//                color = canvasColor,
//                Offset(0.0f, 0.0f),
//                Offset(0.0f, size.height),
//                canvasLineWidth
//            )
//            drawLine(
//                color = canvasColor,
//                Offset(size.width, size.height),
//                Offset(size.width, 0.0f),
//                canvasLineWidth
//            )
//            drawLine(
//                color = canvasColor,
//                Offset(size.width, size.height),
//                Offset(0.0f, size.height),
//                canvasLineWidth
//            )
//            drawCircle(
//                color =  canvasColor,
//                min(size.width, size.height) / 5,
//                Offset(size.width / 2, size.height)
//            )
//            if (pointerPos != null) {
//                if (Communication.pointerPosRel == null) {
//                    Communication.pointerPosRel = Offset(pointerPos!!.x - size.width / 2, pointerPos!!.y)
//                    // Start capturing sound
////                    Communication.readBulk(pointerPosRel!!, context)
//                }
//                drawCircle(
//                    color = canvasColor,
//                    15.0f,
//                    pointerPos!!
//                )
//            } else {
//                if (Communication.pointerPosRel != null) {
//                    Communication.pointerPosRel = null
//                    // Stop capturing sound
////                    Communication.stopReadingBulk()
//                }
//            }
//        }
        AndroidView(factory = {
            context -> GLSurfaceView(context).apply {
                setEGLContextClientVersion(3)
//                setZOrderOnTop(false)
                setRenderer(MyGLRenderer())
                renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
            }
        }, modifier = Modifier.weight(1f).fillMaxHeight().clipToBounds())
        Spacer(modifier = Modifier.weight(0.2f))
    }
}


@Preview(showBackground = true)
@Composable
fun GreetingPreview() {
    SoundLocatorTheme {
        Greeting()
    }
}