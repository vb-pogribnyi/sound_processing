package com.aksemple.soundlocator

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Looper
import android.util.Log
import android.widget.Toast
import androidx.compose.animation.core.StartOffsetType.Companion.Delay
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.geometry.Offset
import androidx.core.content.FileProvider
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Room
import androidx.room.RoomDatabase
import com.aksemple.soundlocator.Communication.Companion.N
import com.aksemple.soundlocator.Communication.Companion.fft
import com.aksemple.soundlocator.Communication.Companion.fftVis
//import com.aksemple.soundlocator.Communication.Companion.isRenderDone
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.logging.Logger
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt
import androidx.compose.ui.graphics.Path
import androidx.room.Query
import kotlinx.coroutines.isActive
import kotlinx.coroutines.runBlocking
import java.io.FileOutputStream
import java.io.RandomAccessFile
import kotlin.collections.mutableListOf
import kotlin.math.sin

const val TAG = "SoundLocator_comm"
private const val ACTION_USB_PERMISSION = "com.aksemple.soundlocator.USB_PERMISSION"

data class CaptureData (
    val bytes: ByteArray,
    val timestamp: Long,
    val nChannels: Int,
    val touchX: Int?,
    val touchY: Int?,
    val isOverrun: Int,
    val motor1Val: Float,
    val motor2Val: Float,
    val micsAngle: Int,
    val note: String
)

@Entity(tableName = "sound_data", indices = [Index(value = ["captureId", "channelId"])])
data class SoundData (
    @PrimaryKey(autoGenerate=true) val id: Long = 0,
    val timestamp: Long,
    val captureId: Long,
    val channelId: Int,
    val value: Int,
)
@Dao
interface SoundDataDao {
    @Insert
    suspend fun insert(rows: List<SoundData>): Unit

    @Query("SELECT * FROM sound_data WHERE captureId = :captureId")
    fun loadByCaptureID(captureId: Int): Array<SoundData>

    @Query("SELECT * FROM sound_data WHERE captureId = :captureId ORDER BY id ASC")
    suspend fun loadByCaptureIdOrdered(captureId: Long): List<SoundData>

    @Query("SELECT * FROM sound_data WHERE captureId = :captureId AND channelId = :channelId ORDER BY id ASC")
    suspend fun loadChannel(captureId: Long, channelId: Int): List<SoundData>

    @Query("SELECT DISTINCT channelId FROM sound_data WHERE captureId = :captureId ORDER BY channelId ASC")
    suspend fun channelsOf(captureId: Long): List<Int>

    /** One channel's samples concatenated across a capture-id range, in arrival order
     *  (by captureId, then row id) - so consecutive captures join end-to-end. */
    @Query("SELECT value FROM sound_data WHERE captureId BETWEEN :minId AND :maxId AND channelId = :channelId ORDER BY captureId ASC, id ASC")
    suspend fun loadChannelRange(minId: Long, maxId: Long, channelId: Int): List<SampleValue>

    /** Per-capture sample count for a channel across a range (to place capture boundaries). */
    @Query("SELECT captureId AS captureId, COUNT(*) AS cnt FROM sound_data WHERE captureId BETWEEN :minId AND :maxId AND channelId = :channelId GROUP BY captureId ORDER BY captureId ASC")
    suspend fun channelCountsInRange(minId: Long, maxId: Long, channelId: Int): List<CaptureSampleCount>
}
@Entity(tableName = "captures")
data class Capture (
    @PrimaryKey(autoGenerate=true) val id: Long = 0,
    val timestamp: Long,
    val nChannels: Int,
    val touchX: Int?,
    val touchY: Int?,
    val isOverrun: Int,
    val motor1Val: Float,
    val motor2Val: Float,
    val micsAngle: Int,
    val note: String
)
/** Projection: number of samples of one channel in a single capture (range boundaries). */
data class CaptureSampleCount(val captureId: Long, val cnt: Int)

/** Projection: a single sample value (single-column range query). */
data class SampleValue(val value: Int)

/** Lightweight projection for the capture browser list (right pane). */
data class CaptureListItem(
    val id: Long,
    val timestamp: Long,
    val nChannels: Int,
    val isOverrun: Int,
    val soundCount: Int
)
@Dao
interface CapturesDao {
    @Insert
    fun insert(row: Capture): Long

    /** Latest-first page of captures, each with its sound_data row count. */
    @Query(
        "SELECT c.id AS id, c.timestamp AS timestamp, c.nChannels AS nChannels, c.isOverrun AS isOverrun, " +
        "(SELECT COUNT(*) FROM sound_data s WHERE s.captureId = c.id) AS soundCount " +
        "FROM captures c ORDER BY c.timestamp DESC, c.id DESC LIMIT :limit OFFSET :offset"
    )
    suspend fun getCapturesPaged(limit: Int, offset: Int): List<CaptureListItem>
}

@Database(entities = [SoundData::class, Capture::class], version=3)
abstract class AppDatabase: RoomDatabase()
{
    abstract fun soundDataDao(): SoundDataDao
    abstract fun capturesDao(): CapturesDao

    companion object {
        @Volatile private var INSTANCE: AppDatabase? = null
        fun getInstance(context: Context): AppDatabase {
            return INSTANCE ?: synchronized(this) {
                val instance = Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "sound_database.db"
                ).fallbackToDestructiveMigration()
                    .build()
                INSTANCE = instance
                instance
            }
        }
    }
}

fun ByteArray.toHexString(): String = joinToString(" ") {"%02X".format(it)}
class Communication {
    private val usbReceiver = object : BroadcastReceiver() {

        override fun onReceive(context: Context, intent: Intent) {
            if (ACTION_USB_PERMISSION == intent.action) {
                synchronized(this) {
                    val device: UsbDevice? = intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)

                    if (intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) {
                        device?.apply {
                            status.value = "Device available"
                        }
                    } else {
                        Log.d(TAG, "permission denied for device $device")
                        status.value = "Permission not granted"
                    }
                }
            }
        }
    }

    companion object {
        var anotherStatus = mutableStateOf("AnotherStatus")
        var bulkReadsSuccess = mutableIntStateOf(0)
        var bulkReadsFail = mutableIntStateOf(0)
        var motor1Val = mutableFloatStateOf(0f)
        var motor2Val = mutableFloatStateOf(0f)
        var micsAngle = mutableIntStateOf(0)
        var note = mutableStateOf("")
        var status = mutableStateOf("Status")
        var bulkTime = mutableFloatStateOf(0.0f)
        var rdyTime = mutableFloatStateOf(0.0f)
        var rqstTime = mutableFloatStateOf(0.0f)
        var epMain = mutableIntStateOf(0)
        var epTrace = mutableIntStateOf(0)
        var epPer = mutableIntStateOf(0)
        var mainBytes = mutableIntStateOf(0)
        var traceBytes = mutableIntStateOf(0)
        var periodicBytes = mutableIntStateOf(0)
        var mainReportedBytes = mutableIntStateOf(0)
        var mainReceivedBytes = mutableIntStateOf(0)
        var interruptStatus = mutableStateOf("IntStatus")
        var interruptData = mutableStateOf("IntData")

        var isTraceRequested = mutableIntStateOf(0)
        var isPeriodicRequested = mutableIntStateOf(0)
        var fftVis = mutableStateOf<Path>(Path())
        var usbManager: UsbManager? = null
        var activeDevice: UsbDevice? = null
        var bulkMainEndpoint: UsbEndpoint? = null
        var bulkPeriodicEndpoint: UsbEndpoint? = null
        var bulkTraceEndpoint: UsbEndpoint? = null
        var intSoundEndpoint: UsbEndpoint? = null
            get() = field
        var intSoundRdyEndpoint: UsbEndpoint? = null
        var intEPSize: Int = 0
        var usbInterface: UsbInterface? = null
        val db = AppDatabase.getInstance(App.context)
        val soundDao = db.soundDataDao()
        val capturesDao = db.capturesDao()


        var seggerFile: File? = null

        var debugWav: File? = null
        private val N = 4096

        val fftBuffer = FloatArray(N)
//        val im = DoubleArray(N)

        fun plotFFT(samples: List<Int>) {
            // Fill only what we have; a packet usually carries far fewer than N samples.
            for (i in 0 until minOf(N, samples.size)) {
                fftBuffer[i] = samples[i].toFloat() / 10000
            }
        }

        // Packet layout: interleaved 16-bit LE samples, nChannels values per time step
        // (t0: ch0,ch1,..,chN-1; t1: ch0,..). Each (sample, channel) becomes one
        // sound_data row; insertion order preserves each channel's sample sequence.
        fun parsePacket(packet: ByteArray, captureId: Long, nChannels: Int): List<SoundData> {
            val rows = mutableListOf<SoundData>()
            if (nChannels < 1) return rows
            val bb = ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN)
            val ch0 = mutableListOf<Int>()          // channel 0 stream feeds the live FFT view
            val bytesPerSample = nChannels * 2
            while (bb.remaining() >= bytesPerSample) {
                val ts = System.currentTimeMillis()
                for (ch in 0 until nChannels) {
                    val v = bb.short.toInt()
                    rows.add(SoundData(timestamp = ts, captureId = captureId, channelId = ch, value = v))
                    if (ch == 0) ch0.add(v)
                }
            }
            plotFFT(ch0)
            return rows
        }

        fun claimDevice() {
            if (usbManager != null) {
                if (activeDevice == null) {
                    val deviceList = usbManager?.deviceList
                    if (deviceList != null && deviceList.isEmpty()) {
                        status.value = "No devices connected"
                    } else {
                        val device = deviceList?.values?.first()
                        status.value = "Requesting permission for device $device"
                        if (device != null) {
                            activeDevice = device
                            activeDevice!!.getInterface(0).also { intf ->
                                for (i in 0 until intf.endpointCount) {
                                    val ep = intf.getEndpoint(i)
                                    if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK &&
                                        ep.direction == UsbConstants.USB_DIR_IN
                                    ) {
                                        if (ep.endpointNumber == 1) {
                                            bulkMainEndpoint = ep
                                        }
                                        else if (ep.endpointNumber == 3) {
                                            bulkTraceEndpoint = ep
                                        }
                                        else {
                                            bulkPeriodicEndpoint = ep
                                        }
                                        usbInterface = intf
                                    }
                                    if (ep.type == UsbConstants.USB_ENDPOINT_XFER_INT &&
                                        ep.direction == UsbConstants.USB_DIR_OUT
                                    ) {
                                        intSoundEndpoint = ep
                                    }
                                    if (ep.type == UsbConstants.USB_ENDPOINT_XFER_INT &&
                                        ep.direction == UsbConstants.USB_DIR_IN
                                    ) {
                                        intSoundRdyEndpoint = ep
                                    }
                                }
                            }
                            if (bulkMainEndpoint == null) {
                                anotherStatus.value =
                                    "Did not find all endpoints!"
                            } else {
                                epMain.intValue = bulkMainEndpoint!!.endpointNumber
                                epTrace.intValue = bulkTraceEndpoint!!.endpointNumber
                                epPer.intValue = bulkPeriodicEndpoint!!.endpointNumber
//                                anotherStatus.value = "" +
//                                        "Bulk: ${bulkMainEndpoint!!.endpointNumber}, " +
//                                        "IntS ${intSoundEndpoint!!.endpointNumber}, " +
//                                        "IntR ${intSoundRdyEndpoint!!.endpointNumber}, " +
//                                        "IntP ${intSoundPeriodicEndpoint!!.endpointNumber}, " +
//                                        "Int ${intEndpoint!!.endpointNumber} ($intEPSize)."
                            }
                        }
                    }
                }
            } else {
                status.value = "No USB Manager!"
            }
        }

        private val MY_CUSTOM_IN_REQUEST_TYPE = 0xCC
        private val MY_CUSTOM_OUT_REQUEST_TYPE = 0x4C
        private val MY_CUSTOM_REQUEST = 0x25
        private val START_SOUND_TRANSFER = 0x25
        private val END_SOUND_TRANSFER = 0x26
        private val START_SEGGER_TRANSFER = 0x27
        private val END_SEGGER_TRANSFER = 0x28
        private val MOTOR_SPEED_REQUEST = 0x27
        private val REQUEST_SEGGER_TRACE = 0x31
        private val REQUEST_PERIODIC_SIGNAL = 0x32

        private var bulkJob: Job? = null
        private var soundPeriodicJob: Job? = null
        private var soundDaoJob: Job? = null
        private var experimentJob: Job? = null
        private var interruptJob: Job? = null
        private val scope = CoroutineScope(Dispatchers.IO)
        private val defaultScope = CoroutineScope(Dispatchers.Default)
        private val channel = Channel<CaptureData>(capacity = 1024*1024*16)
        private val fftVisChannel = Channel<List<Double>>(capacity = 1024*6*4)
        private var isCapturingActive = false
        private var isExperimentActive = false
        private var isIntCapturingActive = false
        private var fft = FFT(N)
        private var periodicTrasfersLength = 0



        var pointerPosRel: Offset? = null

        fun toggleLED() {
            if (activeDevice == null) {
                claimDevice()
            }
            if (activeDevice == null) {
                status.value = "Cant claim device"
            }
            var bytes : ByteArray = byteArrayOf(0x00, 0x01, 0x03, 0x02)
            usbManager?.openDevice(activeDevice)?.apply {
                status.value = "Sending TurnOFF..."
                controlTransfer(MY_CUSTOM_OUT_REQUEST_TYPE, MY_CUSTOM_REQUEST, 0x57, 0x58, bytes, 0, 1000)
            }
        }

        fun sendMotorSpeed(value1 : Float, value2 : Float) {
            // TODO: Make it without claiming device.
            // The function is called only when the device is already opened.
            if (activeDevice == null) {
                claimDevice()
            }
            if (activeDevice == null) {
                status.value = "Cant claim device"
            }
//            var bytes : ByteArray = byteArrayOf((value1 * 255).toInt().toByte(), (value2 * 255).toInt().toByte())
            usbManager?.openDevice(activeDevice)?.apply {
                status.value = "Sending TurnOFF..."
                controlTransfer(MY_CUSTOM_OUT_REQUEST_TYPE, MOTOR_SPEED_REQUEST, ((value1 * 100).toInt() * 100 + value2 * 100).toInt(), 0, null, 0, 1000)
            }
        }

        suspend fun doReadBulk(connection: UsbDeviceConnection, pointerPosIntl: Offset?, isRecord: Boolean = true) {
            var postTime: Float = 0f
            var aroundTime: Float = 0f
            var loopEndTime: Long = 0
            val bytesToRead = 1024*64
            var bytes = ByteArray(bytesToRead)
            var startReadBytes = byteArrayOf(0x01)
            var readyStatusBytes = ByteArray(4)
            val loopStartTime = System.currentTimeMillis()
            val timeStart = System.currentTimeMillis()
            connection.bulkTransfer(
                intSoundEndpoint,
                startReadBytes,
                1,
                15
            )
            val timeRDYStart = System.currentTimeMillis()
            var rdyResult = connection.bulkTransfer(
                intSoundRdyEndpoint,
                readyStatusBytes,
                4,
                100
            )
            val buffer = ByteBuffer.wrap(readyStatusBytes).order(ByteOrder.LITTLE_ENDIAN)
            val sizeAvailable = buffer.short.toInt() and 0xFFFF
            mainReportedBytes.intValue = sizeAvailable
            val nFails = readyStatusBytes[2]
            val nPeriodicOverflows = readyStatusBytes[2]
            // STM32 reports the channel count in byte 3 of the ready-status message
            // (alongside the payload length in bytes 0-1). Default to 1 if unset (0).
            val nChannels = (readyStatusBytes[3].toInt() and 0xFF).coerceAtLeast(1)
            val timeBLKStart = System.currentTimeMillis()
            // 1:1 protocol: the device transmits 0x81 only when it has data (size > 0).
            // Skip the main read on an empty poll so we don't stall on a phantom transfer.
            val transferResult =
                if (sizeAvailable > 0)
                    connection.bulkTransfer(
                        bulkMainEndpoint,
                        bytes,
                        sizeAvailable,
                        450
                    )
                else 0
            mainReceivedBytes.intValue = transferResult
            val timeEnd = System.currentTimeMillis()
            if (transferResult > 0) {
                if (isRecord) {
                    channel.send(
                        CaptureData(
                            bytes = bytes.copyOf(transferResult),
                            timestamp = System.currentTimeMillis(),
                            nChannels = nChannels,
                            touchX = pointerPosIntl?.x?.toInt(),
                            touchY = pointerPosIntl?.y?.toInt(),
                            isOverrun = nFails.toInt(),
                            motor1Val = motor1Val.value.toFloat(),
                            motor2Val = motor2Val.value.toFloat(),
                            micsAngle = micsAngle.value,
                            note = note.value
                        )
                    )
                }
                bulkReadsSuccess.intValue += 1
            } else if (sizeAvailable > 0) {
                bulkReadsFail.intValue += 1   // device reported data but the read failed
            }
            // else: empty poll (size 0) - not a failure, just no new data yet
            aroundTime = 0.7f * aroundTime + 0.3f * (loopStartTime - loopEndTime).toFloat()

            loopEndTime = System.currentTimeMillis()
            postTime = 0.7f * postTime + 0.3f * (loopEndTime - timeEnd).toFloat()

            bulkTime.floatValue = 0.7f * bulkTime.floatValue + 0.3f * (timeEnd - timeBLKStart).toFloat()
            rdyTime.floatValue = 0.7f * rdyTime.floatValue + 0.3f * (timeBLKStart - timeRDYStart).toFloat()
            rqstTime.floatValue = 0.7f * rqstTime.floatValue + 0.3f * (timeRDYStart - timeStart).toFloat()
            status.value = "Available: $transferResult. Time ${bulkTime} \nRDY $rdyResult. PTransfs $periodicTrasfersLength\nFails: $nFails, PerOVF: $nPeriodicOverflows"
            periodicTrasfersLength = 0
        }

        fun readChannel(connection: UsbDeviceConnection, ctrlCommand: Int, result: ByteArray, endpoint: UsbEndpoint): Int {
            val bytes = ByteArray(4)
            connection.controlTransfer(
                MY_CUSTOM_IN_REQUEST_TYPE,
                ctrlCommand,
                0,
                0,
                bytes,
                4,
                200
            )
            var transferResult = -2
            val bb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val sizeAvail = bb.short.toInt()
//            return sizeAvail
            if (sizeAvail > 0) {
                if (result.size < sizeAvail) {
                    throw Exception("Read Channel: Provided array has not enough capacity (${result.size} vs $sizeAvail).")
                }
                transferResult = connection.bulkTransfer(
                    endpoint,
                    result,
                    sizeAvail,
                    450
                )
            } else {
                return sizeAvail
            }
            return transferResult
//            return sizeAvail
        }

        var captureId = 1501
        fun simulateSavedData() {
            var soundDataSim: Array<SoundData> = arrayOf()
            scope.launch {
                while (soundDataSim.isEmpty()) {
                    soundDataSim = soundDao.loadByCaptureID(captureId)
                    captureId += 1
                }
                plotFFT(soundDataSim.filter { it.channelId == 0 }.map { it.value })
            }
        }

        fun startExperiment() {
            if (isCapturingActive) {
                status.value = "Capturing is active. Can't start experiment."
                return
            }
            status.value = "Starting read..."
            isExperimentActive = true
            experimentJob = scope.launch {
                val filenameTrace = System.currentTimeMillis().toString() + "_trace.bin"
                val filenamePer = System.currentTimeMillis().toString() + "_periodic.bin"
                for (m1speed in 20..95 step 10) {
                    if (!isExperimentActive) break
                    motor1Val.floatValue = m1speed.toFloat() / 100f
                    motor2Val.floatValue = 0f
                    runBlocking {
                        readBulk(true, "1_" + filenameTrace, "1_" + filenamePer, 120)
                    }
                }
                for (m2speed in 20..95 step 10) {
                    if (!isExperimentActive) break
                    motor2Val.floatValue = m2speed.toFloat() / 100f
                    motor1Val.floatValue = 0f
                    runBlocking {
                        readBulk(true, "2_" + filenameTrace, "2_" + filenamePer, 120)
                    }
                }
            }
        }
        fun stopExperiment() {

            anotherStatus.value = "Canceling exteriment..."
            isExperimentActive = false
            experimentJob?.cancel()
            experimentJob = null
            motor1Val.value = 0f
            motor2Val.value = 0f
            sendMotorSpeed(motor1Val.value, motor2Val.value)
            anotherStatus.value = "Experiment canceled."
        }

        fun stopReadingBulk() {
            anotherStatus.value = "Canceling job..."
            bulkJob?.cancel()
            soundPeriodicJob?.cancel()
            soundDaoJob?.cancel()
            bulkJob = null
            soundPeriodicJob = null
            soundDaoJob = null
            anotherStatus.value = "Job canceled."
        }

        fun readBulk(
//            context: Context,
            isSendMotors: Boolean = false,
            filenameTrace: String = "trace.bin",
            filenamePer: String = "periodic.wav",
            nIterations: Int = -1
        ) {
            val bytesToRead = 1024*64
            var bytes = ByteArray(bytesToRead)
            if (isExperimentActive) {
                status.value = "Experiment is active. Can't start capturing."
                return
            }
            if (isCapturingActive) return
            if (activeDevice == null) {
                claimDevice()
            }
            if (activeDevice == null) {
                status.value = "Cant claim device"
            }
            val connection = usbManager?.openDevice(activeDevice)
            if (connection != null) {
                connection.claimInterface(activeDevice!!.getInterface(0), true)
                status.value = "Starting read..."

                bulkJob = scope.launch {
                    var seggerStream: FileOutputStream? = null
                    var debugRaf: RandomAccessFile? = null
                    var dataSize = 0
                    var iterationsPassed = 0

                    try {
                        if (isSendMotors) {
                            sendMotorSpeed(motor1Val.floatValue, motor2Val.floatValue)
                        }
                        connection.controlTransfer(
                            MY_CUSTOM_IN_REQUEST_TYPE,
                            START_SOUND_TRANSFER,
                            bytesToRead,
                            0,
                            null,
                            0,
                            1000
                        )
                        if (isTraceRequested.intValue > 0) {
                            seggerFile = File(App.context.cacheDir, filenameTrace)
                            seggerStream = seggerFile!!.outputStream()
                            connection.controlTransfer(
                                MY_CUSTOM_IN_REQUEST_TYPE,
                                START_SEGGER_TRANSFER,
                                bytesToRead,
                                0,
                                null,
                                0,
                                1000
                            )
                        }
                        if (isPeriodicRequested.intValue > 0) {
                            debugWav = File(App.context.cacheDir, filenamePer)
                            debugRaf = RandomAccessFile(debugWav, "rw")
                            writeWavHeader(debugRaf, 16000, 1, 16)
                        }
                        while (isActive && (nIterations < 0 || iterationsPassed < nIterations)) {
                            iterationsPassed += 1
                            val pointerPosIntl = pointerPosRel
                            doReadBulk(connection, pointerPosIntl)
                            if (pointerPosIntl == null) {
                                bulkReadsSuccess.intValue = 0
                                bulkReadsFail.intValue = 0
                            }
                            if (isTraceRequested.intValue > 0) {
                                traceBytes.intValue = readChannel(
                                    connection,
                                    REQUEST_SEGGER_TRACE,
                                    bytes,
                                    bulkTraceEndpoint!!)
                                if (traceBytes.intValue > 0) {
                                    seggerStream?.write(bytes, 0, traceBytes.intValue)
                                }
                            }
                            if (isPeriodicRequested.intValue > 0) {
                                periodicBytes.intValue = readChannel(
                                    connection,
                                    REQUEST_PERIODIC_SIGNAL,
                                    bytes,
                                    bulkPeriodicEndpoint!!)
                                if (periodicBytes.intValue > 0) {
                                    debugRaf!!.write(bytes, 0, periodicBytes.intValue)
                                    dataSize += periodicBytes.intValue
                                }
                            }
//                            break
                        }
                    } finally {
                        connection.controlTransfer(
                            MY_CUSTOM_IN_REQUEST_TYPE,
                            END_SOUND_TRANSFER,
                            bytesToRead,
                            0,
                            null,
                            0,
                            1000
                        )
                        if (isTraceRequested.intValue > 0) {
                            connection.controlTransfer(
                                MY_CUSTOM_IN_REQUEST_TYPE,
                                END_SEGGER_TRANSFER,
                                bytesToRead,
                                0,
                                null,
                                0,
                                1000
                            )
                            seggerStream?.close()
                        }
                        if (isPeriodicRequested.intValue > 0) {
                            updateWavHeader(debugRaf!!, dataSize)
                            debugRaf!!.close()
                        }
                    }
                }
                soundDaoJob = defaultScope.launch {
                    while (isActive) {
                        for (packet in channel) {
                            try {
                                val capture = Capture(
                                    timestamp = packet.timestamp,
                                    nChannels = packet.nChannels,
                                    touchX = packet.touchX,
                                    touchY = packet.touchY,
                                    isOverrun = packet.isOverrun,
                                    motor1Val = packet.motor1Val,
                                    motor2Val = packet.motor2Val,
                                    micsAngle = packet.micsAngle,
                                    note = packet.note
                                )
                                // Finish the whole DB write even if the recording job is
                                // cancelled mid-insert - otherwise a small single-packet
                                // capture loses its sound_data (Capture row + FFT already ran).
                                withContext(NonCancellable) {
                                    val captureId = capturesDao.insert(capture)
                                    val rows = parsePacket(packet.bytes, captureId, packet.nChannels)
                                    soundDao.insert(rows)
                                }
                            } catch (e: Exception) {
                                // One malformed packet must not tear down the whole recorder.
                                Log.e(TAG, "Failed to record capture packet", e)
                            }
                        }
                    }
                }
            }
        }

        fun writeWavHeader(raf: RandomAccessFile, sampleRate: Int, channels: Int, bitsPerSample: Int) {
            val byteRate = sampleRate * channels * bitsPerSample / 8
            val blockAlign = channels * bitsPerSample / 8
            raf.writeBytes("RIFF")
            raf.writeIntLE(0)
            raf.writeBytes("WAVE")
            raf.writeBytes("fmt ")
            raf.writeIntLE(16)
            raf.writeShortLE(1.toShort())
            raf.writeShortLE(channels.toShort())
            raf.writeIntLE(sampleRate)
            raf.writeIntLE(byteRate)
            raf.writeShortLE(blockAlign.toShort())
            raf.writeShortLE(bitsPerSample.toShort())
            raf.writeBytes("data")
            raf.writeIntLE(0)
        }

        fun updateWavHeader(raf: RandomAccessFile, dataSize: Int) {
            val fileSize = dataSize + 36
            raf.seek(4)
            raf.writeIntLE(fileSize)
            raf.seek(40)
            raf.writeIntLE(dataSize)
        }

        fun RandomAccessFile.writeIntLE(value: Int) {
            write(byteArrayOf(
                (value and 0xff).toByte(),
                (value shr 8 and 0xff).toByte(),
                (value shr 16 and 0xff).toByte(),
                (value shr 24 and 0xff).toByte(),
            ))
        }

        fun RandomAccessFile.writeShortLE(value: Short) {
            write(byteArrayOf(
                (value.toInt() and 0xff).toByte(),
                (value.toInt() shr 8 and 0xff).toByte(),
            ))
        }
    }
}