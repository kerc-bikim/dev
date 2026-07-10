import socket
import struct
import zlib
import sys
import datetime
import logging
import logging.handlers

HOST='0.0.0.0'
PORT = 9908

QSCD_LEN=120
qscd20_fmt_string =">Lccc2s3sIfffffffffffffffffffffffffcc2s"

Prefix=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

logName=Prefix+".QSCD.log"
dataName=Prefix+".QSCD20.bin"

logger = logging.getLogger("mylogger")

fomatter = logging.Formatter("[%(levelname)s|%(filename)s:%(lineno)s] %(asctime)s > %(message)s")
fomatter = logging.Formatter("[%(levelname)s] %(asctime)s > %(message)s")

fileHandler = logging.FileHandler(logName)
streamHandler = logging.StreamHandler()


fileHandler.setFormatter(fomatter)
streamHandler.setFormatter(fomatter)

logger.addHandler(fileHandler)
logger.addHandler(streamHandler)
logger.setLevel(logging.DEBUG)

datafd=open(dataName, "wb")


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind( (HOST, PORT) )

SockTimeOut = 2
SockTimeOutCount = 5
timeout_cnt = 0
sock.settimeout(SockTimeOut)    # 3 sec


try:
    while 1 :

        try :
            pmyqscd, addr = sock.recvfrom(QSCD_LEN)
            myqscd = struct.unpack(qscd20_fmt_string, pmyqscd)

            #rtime = UTCDateTime()
            rtime = datetime.datetime.utcnow()

            #dtime = UTCDateTime(myqscd[6])
            dtime = datetime.datetime.utcfromtimestamp(myqscd[6])


            logger.info("#########################################################################")
            logger.info("{:2s}/{:3s}/{} Recv : {} : Now : {} : Diff :{}".format(myqscd[4].decode('utf-8'),
                                                                                myqscd[5].decode('utf-8'),
                                                                                myqscd[34].decode('utf-8'),
                                                                                dtime, rtime,
                                                                                rtime.timestamp - myqscd[6]))

            buf_4_crc = pmyqscd[4:]
            mycrc = zlib.crc32(buf_4_crc)
            if mycrc != myqscd[0]:
                logger.info("     CRC : received {} calculated {} :::: Un-matched ".format(myqscd[0], mycrc))
            else:
                logger.info("     CRC : received {} calculated {}".format(myqscd[0], mycrc))

            logger.info("DQ, DF, R: Q {} T {} R {}".format(myqscd[1], myqscd[2], myqscd[3]))
            logger.info("U-D WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[7], myqscd[8], myqscd[9]))
            logger.info("N-S WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[10], myqscd[11], myqscd[12]))
            logger.info("E-W WMMA : m {:.10f} M {:10f} A {:10f}".format(myqscd[13], myqscd[14], myqscd[15]))

            logger.info("U-D TMM  : m {:.10f} M {:10f}".format(myqscd[16], myqscd[17]))
            logger.info("N-S TMM  : m {:.10f} M {:10f}".format(myqscd[18], myqscd[19]))
            logger.info("E-W TMM  : m {:.10f} M {:10f}".format(myqscd[20], myqscd[21]))

            logger.info("Maximum  : Z {:.10f} N {:10f} E {:10f}".format(myqscd[22], myqscd[23], myqscd[24]))
            logger.info("    PGA  : H {:.10f} T {:10f}".format(myqscd[25], myqscd[26]))

            logger.info(
                " Each SI : Z {:.10f} N {:10f} E {:10f} H {}".format(myqscd[27], myqscd[28], myqscd[29], myqscd[30]))

            logger.info("Correlate: C {:.10f} Ch1 {} Ch2 {}".format(myqscd[31], myqscd[32], myqscd[33]))

            datafd.write(pmyqscd)
            datafd.flush()

        except socket.timeout:
            timeout_cnt += 1
            if (timeout_cnt >= SockTimeOutCount):
                logger.warning("Could not receive data for last "+str(SockTimeOut*SockTimeOutCount) + " secs.")
                timeout_cnt = 0
                continue
        except Exception as e:
            logger.error(f"Error: {e}")

except:
    logger.critical("Unexpected error occured : " + str(sys.exc_info()[0]))

finally:

    datafd.close()

    sock.close()